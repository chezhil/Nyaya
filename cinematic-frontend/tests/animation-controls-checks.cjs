const {chromium}=require('playwright');const fs=require('fs');
(async()=>{const b=await chromium.launch({headless:true,...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{}),args:['--no-sandbox']});const p=await b.newPage({viewport:{width:390,height:844}});await p.goto('http://127.0.0.1:8765/dashboard/',{waitUntil:'networkidle'});const checks=[];function ok(name,passed){checks.push({name,passed});console.log(passed?'PASS':'FAIL',name)}
await p.evaluate(()=>document.documentElement.style.scrollBehavior='auto');
for(const id of ['storm','intelligence','people','command','future']){await p.evaluate(id=>{const h=document.querySelector('#'+id+' h1,#'+id+' h2');scrollTo(0,scrollY+h.getBoundingClientRect().top-innerHeight*.22)},id);await p.waitForTimeout(100);ok('Mobile '+id+' text visible',await p.locator('#'+id+' .reveal-word').evaluateAll(es=>es.every(e=>+getComputedStyle(e).opacity>.95)))}
const ctas=await p.locator('.open-dashboard').count();
for(let i=0;i<ctas;i++){await p.locator('.open-dashboard').nth(i).evaluate(e=>e.click());ok('Dashboard CTA '+(i+1),await p.locator('#dashboard-dialog').evaluate(e=>e.open));await p.locator('#close-dashboard').evaluate(e=>e.click())}
for(let i=0;i<3;i++){await p.locator('.layer-toggle').nth(i).evaluate(e=>e.click());ok('Layer '+i+' toggles',await p.locator('.layer-toggle').nth(i).getAttribute('aria-pressed')==='false')}
for(const d of ['RELEASE','REVIEW','HOLD']){await p.locator('[data-decision="'+d+'"]').evaluate(e=>e.click());ok('Decision '+d,(await p.locator('#decision-detail').innerText()).startsWith(d))}
await p.emulateMedia({reducedMotion:'reduce'});await p.waitForTimeout(100);ok('Reduced motion restores every headline',await p.locator('.reveal-word').evaluateAll(es=>es.every(e=>+getComputedStyle(e).opacity===1)));
fs.writeFileSync('dashboard/tests/animation-controls-results.json',JSON.stringify(checks,null,2));await b.close()})().catch(e=>{console.error(e);process.exit(1)})
