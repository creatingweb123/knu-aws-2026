import type { ButtonHTMLAttributes, ReactNode } from 'react';

import styles from './PrimaryButton.module.css';

interface Props extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'className'> {
  children: ReactNode;
  /** 요청 중이면 누를 수 없다(FE-NFR-03) */
  loading?: boolean;
  variant?: 'primary' | 'secondary';
  /** 화면 아래 고정. 기본 true */
  fixed?: boolean;
}

/** 하단 고정 주 버튼(docs/05 §5.3). 보조 버튼을 함께 둘 때는 fixed={false}로 만들어 BottomActions로 감싼다 */
export function PrimaryButton({
  children,
  loading = false,
  variant = 'primary',
  fixed = true,
  disabled,
  ...rest
}: Props) {
  const button = (
    <button
      type="button"
      {...rest}
      className={`${styles.button} ${variant === 'secondary' ? styles.secondary : ''}`}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
    >
      {children}
    </button>
  );
  return fixed ? <BottomActions>{button}</BottomActions> : button;
}

export function BottomActions({ children }: { children: ReactNode }) {
  return <div className={styles.bottom}>{children}</div>;
}
