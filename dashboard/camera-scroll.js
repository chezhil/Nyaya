/* NYAYA cinematic camera: scroll-coupled environmental movement across five scenes.
   Leaves existing assets, text reveal animation, API and dashboard untouched. */
(() => {
  'use strict';
  const scenes = Array.from(document.querySelectorAll('.scene'));
  if (!scenes.length) return;
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const mobile = window.matchMedia('(max-width: 600px)');
  const origins = ['64% 37%', '54% 53%', '41% 42%', '56% 55%', '54% 38%'];
  const clamp = v => Math.max(0, Math.min(1, v));
  const lerp = (a,b,p) => a + (b - a) * p;
  let waiting = false, frames = 0;
  function render() {
    waiting = false;
    frames++;
    const disabled = reduced.matches || mobile.matches || document.body.classList.contains('paused');
    const height = window.innerHeight || 900;
    for (let i=0; i<scenes.length; i++) {
      const el = scenes[i];
      const bounds = el.getBoundingClientRect();
      if (bounds.bottom < -height/3 || bounds.top > height*1.3) continue;
      // Timeline progresses continuously while the scene traverses the viewport.
      const phase = clamp((height - bounds.top) / (height + bounds.height));
      const signed = 2*phase - 1;
      const dir = i%2 ? -1 : 1;
      const heightScale = Math.min(1.25, Math.max(.65, bounds.height/800));
      // Gentle drift; text and cards move only slightly so their spacing stays readable.
      const envY = -signed * 24 * heightScale;
      const envX = dir * signed * 8;
      // Zoom always covers the drift around this scene's origin, so the image never leaves an empty edge.
      const [ox, oy] = origins[i].split(' ').map(v => parseFloat(v) / 100);
      const needY = Math.abs(envY) / (Math.min(oy, 1 - oy) * Math.max(bounds.height, 1));
      const needX = Math.abs(envX) / (Math.min(ox, 1 - ox) * Math.max(bounds.width, 1));
      const zoom = Math.max(lerp(1.05, 1.03, phase), 1 + Math.max(needX, needY) + 0.004);
      const imageY = -signed * 8 * heightScale;
      const copyY = -signed * 12 * heightScale;
      const hudY = signed * 8 * heightScale;
      const detailX = -dir * signed * 6;
      const detailY = -signed * 5;
      el.style.setProperty('--cinema-origin', origins[i]);
      el.style.setProperty('--cinema-x', disabled ? '0px' : envX.toFixed(1)+'px');
      el.style.setProperty('--cinema-y', disabled ? '0px' : envY.toFixed(1)+'px');
      el.style.setProperty('--cinema-zoom', disabled ? '1' : zoom.toFixed(4));
      el.style.setProperty('--cinema-image-y', disabled ? '0px' : imageY.toFixed(1)+'px');
      el.style.setProperty('--cinema-image-zoom', disabled ? '1' : (1.018 + .012*(1-phase)).toFixed(4));
      el.style.setProperty('--cinema-copy-y', disabled ? '0px' : copyY.toFixed(1)+'px');
      el.style.setProperty('--cinema-hud-y', disabled ? '0px' : hudY.toFixed(1)+'px');
      el.style.setProperty('--cinema-detail-x', disabled ? '0px' : detailX.toFixed(1)+'px');
      el.style.setProperty('--cinema-detail-y', disabled ? '0px' : detailY.toFixed(1)+'px');
      el.style.setProperty('--cinema-vignette', disabled ? '.34' : (.29 + .15*Math.abs(signed)).toFixed(3));
      el.dataset.cameraPhase = phase.toFixed(3);
    }
  }
  function schedule() {if (!waiting) {waiting=true;requestAnimationFrame(render)}}
  window.addEventListener('scroll', schedule, {passive:true});
  window.addEventListener('resize', schedule, {passive:true});
  window.addEventListener('pageshow', schedule);
  reduced.addEventListener('change', schedule);
  mobile.addEventListener('change', schedule);
  document.getElementById('motion')?.addEventListener('click', () => requestAnimationFrame(schedule));
  render();
})();
