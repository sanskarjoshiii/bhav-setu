export default function Section({
  id,
  title,
  description,
  children,
  aside,
}: {
  id?: string;
  title?: string;
  description?: string;
  children: React.ReactNode;
  aside?: React.ReactNode;
}) {
  return (
    <section id={id} className="shell mt-12 scroll-mt-24">
      {(title || aside) && (
        <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
          <div>
            {title && <h2 className="h3">{title}</h2>}
            {description && <p className="mt-1 text-[0.88rem] text-muted">{description}</p>}
          </div>
          {aside}
        </div>
      )}
      {children}
    </section>
  );
}
