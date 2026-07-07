// Logotipo del SOC Dashboard: un hexágono (perímetro seguro) con una línea de
// pulso dentro (monitoreo de eventos en tiempo real). Hereda el color del
// contenedor vía currentColor — el mismo SVG sirve en login, header y favicon.
export default function Logo({ size = 24 }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinejoin="round"
      strokeLinecap="round"
    >
      <path d="M12 2.5 20 7v10l-8 4.5L4 17V7z" />
      <path d="M6.5 12h2.1l1.6-3.2 2.6 6.4 1.6-3.2h3.2" />
    </svg>
  );
}
