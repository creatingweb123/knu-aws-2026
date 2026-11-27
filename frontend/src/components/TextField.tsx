import { useId } from 'react';
import type { InputHTMLAttributes, ReactNode, TextareaHTMLAttributes } from 'react';

import styles from './TextField.module.css';

interface FieldFrameProps {
  id: string;
  label: string;
  hint?: ReactNode;
  error?: string;
  length?: number;
  maxLength?: number;
  children: ReactNode;
}

/** 라벨·글자 수·에러를 공통으로 그린다. 에러는 aria-describedby로 입력칸과 연결한다(FE-NFR-06) */
function FieldFrame({ id, label, hint, error, length, maxLength, children }: FieldFrameProps) {
  return (
    <div className={styles.field}>
      <div className={styles.labelRow}>
        <label htmlFor={id} className={styles.label}>
          {label}
        </label>
        {maxLength !== undefined ? (
          <span className={styles.count} aria-hidden="true">
            {length ?? 0}/{maxLength}
          </span>
        ) : null}
      </div>
      {children}
      {hint && !error ? (
        <p id={`${id}-hint`} className={styles.hint}>
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={`${id}-error`} className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function describedBy(id: string, hint: ReactNode, error?: string): string | undefined {
  if (error) return `${id}-error`;
  if (hint) return `${id}-hint`;
  return undefined;
}

type CommonProps = {
  label: string;
  hint?: ReactNode;
  error?: string;
};

export type TextFieldProps = CommonProps & Omit<InputHTMLAttributes<HTMLInputElement>, 'className'>;

export function TextField({ label, hint, error, id, maxLength, value, ...rest }: TextFieldProps) {
  const autoId = useId();
  const fieldId = id ?? autoId;
  return (
    <FieldFrame
      id={fieldId}
      label={label}
      hint={hint}
      error={error}
      maxLength={maxLength}
      length={String(value ?? '').length}
    >
      <input
        {...rest}
        id={fieldId}
        value={value}
        maxLength={maxLength}
        className={`${styles.input} ${error ? styles.invalid : ''}`}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(fieldId, hint, error)}
      />
    </FieldFrame>
  );
}

export type TextAreaProps = CommonProps &
  Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'className'> & {
    /** letter: 경험 기록 글(큰 글자, 넓은 줄 간격) */
    variant?: 'default' | 'letter';
  };

export function TextArea({
  label,
  hint,
  error,
  id,
  maxLength,
  value,
  rows = 5,
  variant = 'default',
  ...rest
}: TextAreaProps) {
  const autoId = useId();
  const fieldId = id ?? autoId;
  return (
    <FieldFrame
      id={fieldId}
      label={label}
      hint={hint}
      error={error}
      maxLength={maxLength}
      length={String(value ?? '').length}
    >
      <textarea
        {...rest}
        id={fieldId}
        rows={rows}
        value={value}
        maxLength={maxLength}
        className={`${styles.input} ${styles.textarea} ${variant === 'letter' ? styles.letter : ''} ${error ? styles.invalid : ''}`}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(fieldId, hint, error)}
      />
    </FieldFrame>
  );
}
