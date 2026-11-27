# 백엔드 팀 전달 사항: 로컬 로그인 연동 (FE-Q8)

프론트엔드 7b 단계(로컬 백엔드 연동)에서 확인한 내용 중 백엔드 팀이 판단하거나 반영해야 하는 항목이다. 관련 질문은 [docs/08](../../../docs/08-open-questions.md)의 FE-Q8, BE-Q17이다.

작성 시점: 2026-11-27. 개발 PC(Windows, Docker Desktop 29.8.0)에서 확인했다.

## 1. 공식 Floci 태그가 기동되지 않는다

`floci/floci:2.5.0-compat`의 `/usr/local/bin/docker-entrypoint.sh`가 0바이트다. 그래서 `aws` 컨테이너가 `exec format error`로 종료하고, `api`는 `depends_on aws healthy`에 막힌다.

재현:

```powershell
docker run --rm --entrypoint /bin/sh floci/floci:2.5.0-compat -c "stat -c %s /usr/local/bin/docker-entrypoint.sh"
# 결과: 0
```

같은 다이제스트(`sha256:e84b1be9…`)가 Docker Hub의 `2.5.0-compat` 태그와 일치하므로, 재다운로드로는 해결되지 않는다.

임시 대안으로 `floci/floci:nightly-compat`(다이제스트 `sha256:5c696e29…`, 2026-11-27 게시)을 쓰면 엔트리포인트는 4914바이트이고 기동된다. 다만 nightly는 고정 릴리스가 아니므로 Compose에 그대로 넣기에는 부적절하다.

요청: 고정 릴리스 태그를 정하고 `docker-compose.yml`의 `aws.image`에 반영해 달라. 태그를 정할 때 아래 2번 기능이 들어 있는지 확인해 달라.

## 2. 브라우저의 Cognito 호출이 CORS로 막힌다

프론트엔드(`http://localhost:5173`)가 `http://localhost:4566`의 Floci Cognito를 직접 호출한다. Floci는 CORS 사전 요청(OPTIONS)에 405로 응답하고 `Access-Control-Allow-Origin` 헤더를 붙이지 않는다. 브라우저가 응답을 버려서 로그인 화면에 "네트워크 연결을 확인해 주세요"가 뜬다.

확인한 것:
- 호스트에서 직접 보낸 POST는 200으로 응답하지만 CORS 헤더가 없다.
- 브라우저 방식 사전 요청(OPTIONS)은 405이다.

해결 방법: Floci의 전역 CORS 설정을 쓴다. floci-io/floci PR #849에서 추가된 기능으로, 환경 변수 `EXTRA_CORS_ALLOWED_ORIGINS` 또는 `floci.security.extra-cors-allowed-origins`로 설정한다.

```yaml
services:
  aws:
    environment:
      EXTRA_CORS_ALLOWED_ORIGINS: http://localhost:5173
```

이 설정을 넣은 뒤 확인한 결과:
- `OPTIONS http://localhost:4566/`가 204로 응답하고 `Access-Control-Allow-Headers`에 `x-amz-target`, `content-type`이 포함된다.
- 실제 POST 응답에 `Access-Control-Allow-Origin: http://localhost:5173`이 붙는다.
- 프론트엔드에서 시드 사용자 수현으로 로그인에 성공했다.

요청: `docker-compose.yml`의 `aws` 서비스에 위 환경 변수를 넣어 달라. 지금은 개발 PC의 임시 override 파일(`C:\Users\user\AppData\Local\Temp\floci-nightly.override.yml`)에만 있어서, 다른 PC에서는 로그인이 실패한다.

## 3. BE-Q17 로컬 pytest를 아직 실행하지 않았다

`pytest -m local tests/local -s`를 돌리지 않았다. 개발 PC의 전역 Python에 pytest가 없어서 README 5.2절의 방법으로 Python 3.12 가상환경을 만들어야 한다.

요청: 백엔드 쪽에서 이 테스트를 돌려 `test_seed_user_login_and_me_nickname` 결과를 docs/08 BE-Q17에 기록해 달라. 프론트엔드의 브라우저 로그인 확인은 이미 끝났다.

## 4. 참고: Floci 로그의 반복 경고

`aws` 컨테이너 로그에 5초마다 `recoverable I/O exception ... unix://localhost:2375`가 찍힌다. Floci가 Docker 소켓에 연결하지 못해 재시도하는 것으로 보인다. 로그인과 API 동작에는 영향이 없어 보였지만, 원인은 확인하지 않았다.

요청: 이 경고가 무해한지, 어떤 기능이 Docker 소켓을 쓰는지 확인해 달라.
