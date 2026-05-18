
type Variant = 'loading' | 'success' | 'error' | 'info' | 'warning';

interface Props {
  variant: Variant;
  message: string;
}

const ICON: Record<Variant, string> = {
  loading: '⏳',
  success: '✅',
  error: '❌',
  info: 'ℹ️',
  warning: '⚠️',
};

export default function StatusBadge({ variant, message }: Props) {
  return (
    <div className={`status-badge status-badge--${variant}`} role="status" aria-live="polite">
      <span className="status-badge__icon">{ICON[variant]}</span>
      <span className="status-badge__message">{message}</span>
    </div>
  );
}
