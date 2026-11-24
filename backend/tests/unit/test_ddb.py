"""transact_with_retry 실패 처리 (§2.6 공통 실패 처리).

Validates: Requirements 4.9, 4.10, 4.11
"""

import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.stub import Stubber

from common.ddb import BACKOFF_SECONDS, ConditionFailed, transact_with_retry
from common.errors import ApiError

ITEMS = [
    {"Put": {"TableName": "HaruTable", "Item": {"PK": "PLAN#p1", "SK": "META"}, "ConditionExpression": "attribute_not_exists(PK)"}},
    {"Put": {"TableName": "HaruTable", "Item": {"PK": "IDEM#u#k", "SK": "META"}, "ConditionExpression": "attribute_not_exists(PK)"}},
]


@pytest.fixture
def stubbed():
    client = boto3.resource(
        "dynamodb", region_name="ap-northeast-2", aws_access_key_id="test", aws_secret_access_key="test"
    ).Table("HaruTable").meta.client
    with Stubber(client) as stub:
        yield client, stub
        stub.assert_no_pending_responses()


def cancel(stub, *codes):
    stub.add_client_error(
        "transact_write_items",
        service_error_code="TransactionCanceledException",
        modeled_fields={"CancellationReasons": [{"Code": c} for c in codes]},
    )


def success(stub):
    stub.add_response("transact_write_items", {})


def test_success_first_try(stubbed):
    client, stub = stubbed
    success(stub)
    sleeps = []
    transact_with_retry(ITEMS, client=client, sleep=sleeps.append)
    assert sleeps == []


def test_conflict_then_success(stubbed):
    client, stub = stubbed
    cancel(stub, "TransactionConflict", "None")
    cancel(stub, "None", "TransactionConflict")
    success(stub)
    sleeps = []
    transact_with_retry(ITEMS, client=client, sleep=sleeps.append)
    assert sleeps == [0.05, 0.1]


def test_conflict_exhausted_is_try_again(stubbed):
    client, stub = stubbed
    for _ in range(len(BACKOFF_SECONDS) + 1):  # 첫 시도 + 재시도 3회
        cancel(stub, "TransactionConflict", "None")
    sleeps = []
    with pytest.raises(ApiError) as exc:
        transact_with_retry(ITEMS, client=client, sleep=sleeps.append)
    assert exc.value.code == "TRY_AGAIN" and exc.value.status == 503
    assert sleeps == [0.05, 0.1, 0.2]


def test_condition_failed_no_retry(stubbed):
    client, stub = stubbed
    cancel(stub, "None", "ConditionalCheckFailed")
    sleeps = []
    with pytest.raises(ConditionFailed) as exc:
        transact_with_retry(ITEMS, client=client, sleep=sleeps.append)
    assert exc.value.reasons == ["None", "ConditionalCheckFailed"]
    assert sleeps == []


def test_conflict_mixed_with_condition_retries(stubbed):
    # §2.6: TransactionConflict가 하나라도 있으면 재시도한다.
    client, stub = stubbed
    cancel(stub, "ConditionalCheckFailed", "TransactionConflict")
    cancel(stub, "None", "ConditionalCheckFailed")
    sleeps = []
    with pytest.raises(ConditionFailed):
        transact_with_retry(ITEMS, client=client, sleep=sleeps.append)
    assert sleeps == [0.05]


def test_other_cancellation_is_raised(stubbed):
    client, stub = stubbed
    cancel(stub, "ValidationError", "None")
    with pytest.raises(ClientError):
        transact_with_retry(ITEMS, client=client, sleep=lambda s: None)


def test_non_transaction_error_is_raised(stubbed):
    client, stub = stubbed
    stub.add_client_error("transact_write_items", service_error_code="ProvisionedThroughputExceededException")
    with pytest.raises(ClientError):
        transact_with_retry(ITEMS, client=client, sleep=lambda s: None)
