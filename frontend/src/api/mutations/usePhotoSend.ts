import { useMutation, useQueryClient } from '@tanstack/react-query';

import { markUploadFailed, startSending } from '../../state/sendingClock';
import { photoMeta } from '../../utils/photo';
import { request } from '../client';
import { meKey } from '../queries/useMe';
import { recordKey } from '../queries/useRecord';
import type { PutRecordResponse, ReplacePhotoResponse, UploadInstruction } from '../types';
import { uploadPhoto } from '../upload';

/** 업로드를 시작하고 결과를 기록한다. 업로드 실패는 던지지 않고 `uploaded: false`로 돌려준다(FE-Q23) */
async function upload(
  claimId: string,
  instruction: UploadInstruction,
  file: File,
): Promise<{ uploaded: boolean }> {
  startSending(claimId);
  try {
    await uploadPhoto(instruction, file);
    return { uploaded: true };
  } catch {
    markUploadFailed(claimId);
    return { uploaded: false };
  }
}

/**
 * 사진과 방문 기록 보내기(FE-REC-04): `PUT /record { letter, photo }` → presigned PUT.
 * `PUT /record`의 오류(CLAIM_NOT_ACTIVE 등)는 던진다. 화면은 성공하면 보내는 중으로 간다.
 */
export function useSendWithPhoto(claimId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ letter, file }: { letter: string; file: File }) => {
      const res = await request<PutRecordResponse>(`/claims/${encodeURIComponent(claimId)}/record`, {
        method: 'PUT',
        body: { letter, photo: photoMeta(file) },
      });
      if (!res.upload) return { uploaded: false };
      return upload(claimId, res.upload, file);
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: recordKey(claimId) });
      void queryClient.invalidateQueries({ queryKey: meKey });
    },
  });
}

/** 사진 교체(FE-REC-09): `POST /record/photo { contentType, size }` → presigned PUT */
export function useReplacePhoto(claimId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (file: File) => {
      const res = await request<ReplacePhotoResponse>(`/claims/${encodeURIComponent(claimId)}/record/photo`, {
        method: 'POST',
        body: photoMeta(file),
      });
      return upload(claimId, res.upload, file);
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: recordKey(claimId) });
      void queryClient.invalidateQueries({ queryKey: meKey });
    },
  });
}
