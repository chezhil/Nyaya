(() => {
'use strict';
const scenes=[...document.querySelectorAll('.scene')],audio=new window.NyayaAudio(),sound=document.querySelector('#sound'),motion=document.querySelector('#motion'),dialog=document.querySelector('#dashboard-dialog'),frame=document.querySelector('#dashboard-frame');
const reduced=matchMedia('(prefers-reduced-motion: reduce)');
let paused=reduced.matches,quality='balanced',active=0,last=0,raf=0,nextLightning=performance.now()+9000,pendingTab='tab-xray',lastFocus=null;
const states=scenes.map((el,i)=>({el,canvas:el.querySelector('canvas'),ctx:el.querySelector('canvas')?.getContext('2d'),width:0,height:0,visible:false,particles:[],index:i}));
function syncMotion(){document.body.classList.toggle('paused',paused);document.body.classList.toggle('reduced',reduced.matches);motion.disabled=reduced.matches;motion.textContent=reduced.matches?'Reduced motion':paused?'Resume motion':'Pause motion';motion.setAttribute('aria-pressed',String(paused));if(paused)states.forEach(s=>s.ctx?.clearRect(0,0,s.width,s.height));}
syncMotion();reduced.addEventListener('change',()=>{paused=reduced.matches;syncMotion();});
motion.addEventListener('click',()=>{paused=!paused;syncMotion();});
sound.addEventListener('click',async()=>{sound.disabled=true;try{const enabled=await audio.toggle();sound.textContent=enabled?'◉ Sound ON':'◌ Sound OFF';sound.setAttribute('aria-pressed',String(enabled));document.querySelector('#audio-status').textContent=enabled?'Sound enabled':'Sound muted';}catch(e){document.querySelector('#audio-status').textContent=e.message;sound.textContent='Sound unavailable';}finally{sound.disabled=false;}});
document.querySelector('#volume').addEventListener('input',e=>audio.setVolume(Number(e.target.value)/100));
document.querySelector('#quality').addEventListener('change',e=>{quality=e.target.value;document.body.classList.toggle('lite',quality==='lite');resize();});
function resize(){states.forEach(s=>{if(!s.canvas)return;const r=s.el.querySelector('.stage').getBoundingClientRect();s.width=r.width;s.height=r.height;const dpr=Math.min(devicePixelRatio||1,quality==='high'?2:1.25);s.canvas.width=Math.round(r.width*dpr);s.canvas.height=Math.round(r.height*dpr);s.ctx?.setTransform(dpr,0,0,dpr,0,0);const count=quality==='lite'?22:quality==='high'?180:85;s.particles=Array.from({length:count},()=>({x:Math.random()*r.width,y:Math.random()*r.height,s:Math.random()+.4}));});}
const ro=new ResizeObserver(resize);scenes.forEach(s=>ro.observe(s));resize();
const io=new IntersectionObserver(entries=>{entries.forEach(e=>{const s=states.find(s=>s.el===e.target);s.visible=e.isIntersecting;e.target.classList.toggle('is-hidden',!e.isIntersecting);});},{rootMargin:'80px'});scenes.forEach(s=>io.observe(s));
function draw(s,dt){const c=s.ctx;if(!c)return;c.clearRect(0,0,s.width,s.height);if(paused)return;const stars=s.index===4;c.strokeStyle=stars?'rgba(255,215,157,.48)':'rgba(174,220,243,.4)';c.fillStyle='#ffe2ad';c.lineWidth=.8;s.particles.forEach(p=>{p.y+=(stars?-9:260)*p.s*dt;p.x+=(stars?5:-75)*p.s*dt;if(p.y>s.height){p.y=-20;p.x=Math.random()*s.width;}if(p.y< -20)p.y=s.height;if(p.x<0)p.x=s.width;if(p.x>s.width)p.x=0;if(stars){c.globalAlpha=.3+.3*Math.sin(p.x);c.fillRect(p.x,p.y,p.s*1.5,p.s*1.5);}else{c.beginPath();c.moveTo(p.x,p.y);c.lineTo(p.x+5*p.s,p.y-18*p.s);c.stroke();}});c.globalAlpha=1;}
function tick(time){const dt=Math.min((time-last)/1000||.016,.05);last=time;let nearest=Infinity,chosen=active;
 states.forEach(s=>{if(!s.visible)return;const r=s.el.getBoundingClientRect(),progress=Math.max(0,Math.min(1,(innerHeight-r.top)/(innerHeight+r.height)));const distance=Math.abs(r.top+r.height/2-innerHeight/2);if(distance<nearest){nearest=distance;chosen=s.index;}if(!paused){s.el.style.setProperty('--camera',String(1+progress*.024));s.el.style.setProperty('--sun',String(.15+.85*progress));}draw(s,dt);});
 if(chosen!==active){active=chosen;audio.setScene(active);}
 if(!paused&&active===0&&time>nextLightning&&!dialog.open){const flash=scenes[0].querySelector('.flash');flash.classList.add('strike');audio.thunder();setTimeout(()=>flash.classList.remove('strike'),170);nextLightning=time+11000+Math.random()*12000;}
 raf=requestAnimationFrame(tick);
}
raf=requestAnimationFrame(tick);
document.addEventListener('visibilitychange',()=>{audio.visibility().catch(()=>{});if(document.hidden)cancelAnimationFrame(raf);else{last=performance.now();raf=requestAnimationFrame(tick);}});
document.querySelectorAll('.layer-toggle').forEach(btn=>btn.addEventListener('click',()=>{const enabled=btn.getAttribute('aria-pressed')!=='true';btn.setAttribute('aria-pressed',String(enabled));btn.querySelector('span').textContent=enabled?'ON':'OFF';scenes[1].querySelector('.'+btn.dataset.layer)?.classList.toggle('layer-off',!enabled);audio.click();}));
const definitions={RELEASE:'RELEASE: the engine permits the full payment.',REVIEW:'REVIEW: a policy-limited survival stipend is paid now; the remainder enters escrow with analyst review and the documented auto-release rule.',HOLD:'HOLD: the engine blocks the payment. A customer can appeal through the dashboard.'};
document.querySelectorAll('[data-decision]').forEach(btn=>btn.addEventListener('click',()=>{document.querySelector('#decision-detail').textContent=definitions[btn.dataset.decision];audio.click();}));
function selectDashboardTab(){try{if(frame.contentWindow?.nyayaDashboardReady&&frame.contentWindow?.switchTab)frame.contentWindow.switchTab(pendingTab);}catch{/* Direct dashboard link remains available if embedding is restricted. */}}
frame.addEventListener('load',selectDashboardTab);
// The dashboard opens as its own full-screen page (not a floating dialog); the URL hash picks the tab.
document.querySelectorAll('.open-dashboard').forEach(btn=>btn.addEventListener('click',()=>{audio.duck(true);try{sessionStorage.setItem('nyaya-story-y',String(Math.round(scrollY)));}catch{}window.location.assign('dashboard.html#'+(btn.dataset.tab||'tab-xray'));}));
// Coming back from the dashboard ('Return to Story' links to #resume, or the browser's Back button):
// put the reader where they left the story, then tidy the URL.
try{const nav=performance.getEntriesByType('navigation')[0];const y=Number(sessionStorage.getItem('nyaya-story-y'));const resume=location.hash==='#resume';
 if((resume||(nav&&nav.type==='back_forward'))&&y>0){const go=()=>window.scrollTo({top:y,behavior:'instant'});requestAnimationFrame(go);
  // Re-apply once everything has loaded: the browser's own hash/scroll handling can run after our first attempt.
  if(document.readyState==='complete')setTimeout(go,60);else addEventListener('load',()=>setTimeout(go,60),{once:true});}
 if(resume)history.replaceState(null,'',location.pathname+location.search);}catch{}
document.querySelector('#close-dashboard').addEventListener('click',()=>dialog.close());
dialog.addEventListener('close',()=>{audio.duck(false);try{frame.contentWindow?.pauseReplay?.();}catch{}lastFocus?.focus();});
// Recorded suite is deliberately fetched directly; landing-page visits never invoke banking endpoints.
fetch('fixtures/simulate.json').then(r=>{if(!r.ok)throw Error('No recorded suite');return r.json();}).then(data=>{
 const l=data.metrics?.legacy?.victims_left_with_zero_rate,n=data.metrics?.nyaya?.victims_left_with_zero_rate;
 if(Number.isFinite(l)&&Number.isFinite(n)){document.querySelector('#evidence-comparison').textContent=`${(l*100).toFixed(1)}% → ${(n*100).toFixed(2)}%`;document.querySelector('#evidence-source').textContent=`Victims left with ₹0 · ${Number(data.suite?.rows||0).toLocaleString('en-IN')}-payment synthetic suite · recorded on LinuxONE`;}
}).catch(()=>{document.querySelector('#evidence-source').textContent='Recorded suite unavailable. Open dashboard to inspect API status.';});
window.addEventListener('pagehide',e=>{cancelAnimationFrame(raf);if(e.persisted){audio.ctx?.suspend();}else{audio.dispose();ro.disconnect();io.disconnect();}});
window.addEventListener('pageshow',e=>{if(e.persisted){last=performance.now();raf=requestAnimationFrame(tick);if(audio.enabled)audio.ctx?.resume().catch(()=>{});}});
})();
