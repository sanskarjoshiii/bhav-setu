import Link from "next/link";

export default function NotFound() {
  return (
    <div className="shell grid min-h-[60vh] place-items-center text-center">
      <div>
        <p className="eyebrow">404</p>
        <h1 className="h2 mt-3">That page is not in the mandi.</h1>
        <p className="lede mx-auto mt-3 max-w-sm">
          The link may be old, or we may have moved it.
        </p>
        <Link href="/" className="btn-primary mt-7">
          Back to home
        </Link>
      </div>
    </div>
  );
}
