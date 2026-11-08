type Props = {
  mark?: boolean;
  decorative?: boolean;
  className?: string;
};

export default function BrandLogo({ mark = false, decorative = false, className = '' }: Props) {
  return (
    <img
      className={`brand-logo ${mark ? 'brand-logo-mark' : 'brand-logo-lockup'} ${className}`.trim()}
      src={`/brand/${mark ? 'KNOT-mark' : 'KNOT-logo'}.svg`}
      alt={decorative ? '' : 'KNOT'}
      width={mark ? 128 : 458}
      height={128}
      draggable={false}
    />
  );
}

export function HomeLogo({ onHome, className = '' }: { onHome?: () => void; className?: string }) {
  return (
    <a
      className={`home-logo-link ${className}`.trim()}
      href="#"
      aria-label="KNOT home"
      onClick={
        onHome
          ? (event) => {
              event.preventDefault();
              onHome();
            }
          : undefined
      }
    >
      <BrandLogo decorative />
    </a>
  );
}
