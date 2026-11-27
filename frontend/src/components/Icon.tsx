import type { ReactNode } from 'react';

/** 선 아이콘 모음(docs/05 §5.3). 장식용이라 항상 aria-hidden이다. 이름이 필요하면 감싼 버튼·링크에 aria-label을 단다 */
export type IconName =
  | 'back'
  | 'mail'
  | 'ticket'
  | 'grid'
  | 'calendar'
  | 'inbox'
  | 'clock'
  | 'plus'
  | 'chevron'
  | 'check'
  | 'alert'
  | 'info'
  | 'shield'
  | 'chat'
  | 'camera'
  | 'image'
  | 'copy'
  | 'send'
  | 'timer'
  | 'spark'
  | 'pencil';

const PATHS: { [k in IconName]: ReactNode } = {
  back: <path d="M15 5l-7 7 7 7" />,
  mail: (
    <>
      <rect x="3" y="6" width="18" height="13" rx="2" />
      <path d="M3.5 7l8.5 6 8.5-6" />
    </>
  ),
  ticket: (
    <>
      <path d="M3 7h18v3a2 2 0 000 4v3H3v-3a2 2 0 000-4z" />
      <path d="M15 7v10" strokeDasharray="2 2" />
    </>
  ),
  grid: (
    <>
      <rect x="4" y="4" width="7" height="7" rx="1.5" />
      <rect x="13" y="4" width="7" height="7" rx="1.5" />
      <rect x="4" y="13" width="7" height="7" rx="1.5" />
      <rect x="13" y="13" width="7" height="7" rx="1.5" />
    </>
  ),
  calendar: (
    <>
      <rect x="4" y="5" width="16" height="15" rx="2" />
      <path d="M4 10h16M9 3v4M15 3v4" />
    </>
  ),
  inbox: (
    <>
      <path d="M4 13l2.5-7h11l2.5 7v6H4z" />
      <path d="M4 13h5l1 2h4l1-2h5" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </>
  ),
  plus: <path d="M12 5v14M5 12h14" />,
  chevron: <path d="M9 5l7 7-7 7" />,
  check: <path d="M5 12l5 5 9-10" />,
  alert: (
    <>
      <path d="M12 6v8" />
      <path d="M12 17.5v.5" />
    </>
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5" />
      <path d="M12 7.5v.5" />
    </>
  ),
  shield: <path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z" />,
  chat: <path d="M21 12a8 8 0 01-11.6 7.1L4 20l1-4.6A8 8 0 1121 12z" />,
  camera: (
    <>
      <rect x="3" y="6" width="18" height="14" rx="2" />
      <circle cx="12" cy="13" r="3.5" />
      <path d="M8 6l1.5-2h5L16 6" />
    </>
  ),
  image: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <circle cx="9" cy="10" r="2" />
      <path d="M21 16l-5-5-9 9" />
    </>
  ),
  copy: (
    <>
      <rect x="8" y="8" width="12" height="12" rx="2" />
      <path d="M16 8V5a1 1 0 00-1-1H5a1 1 0 00-1 1v10a1 1 0 001 1h3" />
    </>
  ),
  send: <path d="M4 12l16-8-6 16-3-7z" />,
  timer: (
    <>
      <circle cx="12" cy="13" r="8" />
      <path d="M12 9v4l2.5 2" />
      <path d="M9 3h6" />
    </>
  ),
  spark: <path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5L18 18M18 6l-2.5 2.5M8.5 15.5L6 18" />,
  pencil: (
    <>
      <path d="M4 20h4L19 9l-4-4L4 16z" />
      <path d="M13 7l4 4" />
    </>
  ),
};

interface Props {
  name: IconName;
  size?: number;
  strokeWidth?: number;
  className?: string;
}

export function Icon({ name, size = 24, strokeWidth = 1.8, className }: Props) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className={className}
    >
      {PATHS[name]}
    </svg>
  );
}
