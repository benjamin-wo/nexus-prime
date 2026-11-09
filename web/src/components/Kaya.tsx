/** Kaya, the kaya-toast mascot. Decorative by default (`alt=""`); give it a name with `alt="Kaya"` where it
 * stands for something on its own. The small versions use the sprites in `public/` (64px, and 128px for
 * sharp screens), so a small mascot never loads the big cut-out; only `big` does. */
export function Kaya({
  size = 32,
  big = false,
  alt = "",
  className,
  lazy = false,
}: {
  size?: number;
  big?: boolean;
  alt?: string;
  className?: string;
  /** For a mascot that is not on screen at first (a chat message, an empty state further down). */
  lazy?: boolean;
}) {
  const classes = `kaya${className ? ` ${className}` : ""}`;
  if (big) {
    // The cut-out is 467 by 450.
    return (
      <img className={classes} src="/kaya.png" alt={alt} width={size} height={Math.round((size * 450) / 467)} decoding="async" />
    );
  }
  return (
    <img
      className={classes}
      src="/kaya-64.png"
      srcSet="/kaya-64.png 1x, /kaya-128.png 2x"
      alt={alt}
      width={size}
      height={size}
      decoding="async"
      loading={lazy ? "lazy" : undefined}
    />
  );
}
