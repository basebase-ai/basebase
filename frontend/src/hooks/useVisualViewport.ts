import { useEffect } from 'react';

/**
 * Track the visual viewport on mobile and set CSS custom properties so the
 * app container always matches the actually-visible area.  This prevents
 * the virtual keyboard from pushing the header off-screen on iOS / Android.
 *
 * Sets:
 *   --app-height   – visual viewport height (px)
 *   --app-offset   – visual viewport offsetTop (px) to reposition fixed body
 */
export function useVisualViewport(): void {
  useEffect(() => {
    const vv: VisualViewport | null = window.visualViewport ?? null;
    if (!vv) return;

    const update = (): void => {
      document.documentElement.style.setProperty('--app-height', `${vv.height}px`);
      document.documentElement.style.setProperty('--app-offset', `${vv.offsetTop}px`);
    };

    update();
    vv.addEventListener('resize', update);
    vv.addEventListener('scroll', update);

    return () => {
      vv.removeEventListener('resize', update);
      vv.removeEventListener('scroll', update);
    };
  }, []);
}
