/* Native scroll timeline: deterministic in both directions; no scroll hijacking. */
(() => {
 'use strict';
 const reduced=matchMedia('(prefers-reduced-motion: reduce)');
 const scenes=[...document.querySelectorAll('.scene')];
 const clamp=x=>Math.max(0,Math.min(1,x));
 const smooth=x=>{x=clamp(x);return x*x*(3-2*x)};
 const headings=[...document.querySelectorAll('.copy h1,.copy h2')].map(el=>{
  const label=el.innerText.replace(/\s+/g,' ').trim();
  const walker=document.createTreeWalker(el,NodeFilter.SHOW_TEXT);const nodes=[];
  while(walker.nextNode())nodes.push(walker.currentNode);
  for(const node of nodes){const f=document.createDocumentFragment();for(const token of node.textContent.split(/(\s+)/)){if(!token)continue;if(/^\s+$/.test(token)){f.append(document.createTextNode(token));continue}const span=document.createElement('span');span.className='reveal-word';span.textContent=token;span.setAttribute('aria-hidden','true');f.append(span)}node.replaceWith(f)}
  el.setAttribute('aria-label',label);
  return {el,words:[...el.querySelectorAll('.reveal-word')]};
 });
 const items=[...document.querySelectorAll('.copy p,.copy .eyebrow,.copy .primary,.copy .text-link,.glass,.future-mantra')];
 // Individual transform properties leave the existing camera and foreground animations intact.
 let scheduled=false;
 function paint(){scheduled=false;const vh=innerHeight;const still=reduced.matches||document.body.classList.contains('paused');
  for(const {el,words} of headings){const r=el.getBoundingClientRect();const entry=smooth((vh*.94-r.top)/(vh*.52));const leave=smooth((r.bottom-vh*.07)/(vh*.2));
   words.forEach((word,i)=>{const t=still?1:smooth((entry-i/Math.max(words.length,1)*.26)/.74);const a=still?1:t*leave;word.style.opacity=a.toFixed(3);word.style.transform=`translateY(${((1-t)*24-(1-leave)*16).toFixed(2)}px) scale(${(.96+.04*t).toFixed(3)})`;word.style.filter=a>.995?'none':`blur(${((1-t)*5).toFixed(2)}px)`;word.style.clipPath=t>.995?'none':`inset(0 0 ${((1-t)*95).toFixed(1)}% 0)`;});
  }
  for(const el of items){const r=el.getBoundingClientRect();const a=still?1:smooth((vh*.98-r.top)/(vh*.25))*smooth((r.bottom-vh*.015)/(vh*.12));el.style.opacity=a.toFixed(3);}
  for(const scene of scenes){const r=scene.getBoundingClientRect();if(r.bottom<0||r.top>vh)continue;const progress=clamp((vh-r.top)/(vh+r.height));scene.style.setProperty('--story-depth',still?'0px':`${((progress-.5)*22).toFixed(2)}px`);scene.style.setProperty('--story-glow',(still?0:Math.sin(progress*Math.PI)*.1).toFixed(3));}
 }
 function schedule(){if(!scheduled){scheduled=true;requestAnimationFrame(paint)}}
 addEventListener('scroll',schedule,{passive:true});addEventListener('resize',schedule,{passive:true});addEventListener('pageshow',schedule);reduced.addEventListener('change',schedule);
 document.querySelector('#motion')?.addEventListener('click',schedule);
 document.addEventListener('focusin',e=>{const panel=e.target.closest('.copy,.glass');if(panel){panel.style.opacity='1';panel.querySelectorAll('.reveal-word').forEach(w=>{w.style.opacity='1';w.style.transform='none';w.style.filter='none';w.style.clipPath='none'})}});
 document.documentElement.classList.add('story-motion-ready');paint();
})();
