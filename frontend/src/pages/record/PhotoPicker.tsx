import { useEffect, useId, useState } from 'react';

import { PHOTO_TYPES, validatePhoto } from '../../utils/photo';
import styles from './Record.module.css';

interface Props {
  file: File | null;
  onChange: (file: File | null) => void;
  /** 서버가 돌려준 사진 오류(`details.photo`) */
  serverError?: string;
  label?: string;
}

/**
 * 사진 1장 선택(FE-REC-03): JPEG·PNG, 10MB 이하만 받는다. 미리보기 URL은 바꾸거나 떠날 때 해제한다.
 * 작성(5)과 교체(5-3)에서 같이 쓴다.
 */
export function PhotoPicker({ file, onChange, serverError, label = '사진 (선택, 1장)' }: Props) {
  const id = useId();
  const [error, setError] = useState<string>();
  const preview = usePreviewUrl(file);
  const shown = error ?? serverError;

  return (
    <div className={styles.photoField}>
      <label htmlFor={id} className={styles.photoLabel}>
        {label}
      </label>
      {file ? (
        <div className={styles.photoPreview}>
          {preview ? <img src={preview} alt="고른 사진 미리보기" className={styles.photoImg} /> : null}
          <p className={styles.photoName}>{file.name}</p>
          <button type="button" className={styles.copy} onClick={() => onChange(null)}>
            사진 빼기
          </button>
        </div>
      ) : null}
      <input
        id={id}
        type="file"
        accept={PHOTO_TYPES.join(',')}
        className={styles.photoInput}
        aria-invalid={shown ? true : undefined}
        aria-describedby={shown ? `${id}-error` : undefined}
        onChange={(e) => {
          const picked = e.target.files?.[0] ?? null;
          e.target.value = '';
          if (!picked) return;
          const problem = validatePhoto(picked);
          setError(problem ?? undefined);
          if (!problem) onChange(picked);
        }}
      />
      {shown ? (
        <p id={`${id}-error`} className={styles.photoError} role="alert">
          {shown}
        </p>
      ) : null}
    </div>
  );
}

function usePreviewUrl(file: File | null): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    // jsdom 등 createObjectURL이 없는 환경에서는 미리보기 없이 이름만 보여 준다
    if (!file || typeof URL.createObjectURL !== 'function') {
      setUrl(null);
      return;
    }
    const next = URL.createObjectURL(file);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [file]);
  return url;
}
