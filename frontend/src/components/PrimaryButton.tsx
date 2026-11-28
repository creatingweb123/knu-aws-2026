import { forwardRef } from 'react';
import type { ButtonHTMLAttributes, ReactNode } from 'react';

import styles from './PrimaryButton.module.css';

interface Props extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'className'> {
  children: ReactNode;
  /** 요청 중이면 누를 수 없다(FE-NFR-03) */
  loading?: boolean;
  /** danger: 되돌리기 어려운 동작(이어받기 포기). 보조 버튼 모양에 빨간 글자(docs/05 §5.3) */
  variant?: 'primary' | 'secondary' | 'danger';
  /** 화면 아래 고정. 기본 true */
  fixed?: boolean;
}

const VARIANT = { primary: '', secondary: styles.secondary, danger: styles.danger } as const;

/** 하단 고정 주 버튼(docs/05 §5.3). 보조 버튼을 함께 둘 때는 fixed={false}로 만들어 BottomActions로 감싼다 */
export const PrimaryButton = forwardRef<HTMLButtonElement, Props>(function PrimaryButton(
  { children, loading = false, variant = 'primary', fixed = true, disabled, ...rest },
  ref,
) {
  const button = (
    <button
      ref={ref}
      type="button"
      {...rest}
      className={`${styles.button} ${VARIANT[variant]}`}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
    >
      {children}
    </button>
  );
  return fixed ? <BottomActions>{button}</BottomActions> : button;
});

/** 하단 고정 버튼 영역. hint는 버튼 위 한 줄 안내(예: 이어받기 기한) */
export function BottomActions({ children, hint }: { children: ReactNode; hint?: ReactNode }) {
  return (
    <div className={styles.bottom}>
      {hint ? <p className={styles.hint}>{hint}</p> : null}
      {children}
    </div>
  );
}
