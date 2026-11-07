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
