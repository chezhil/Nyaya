const {chromium}=require('playwright');
const fs=require('fs');
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{}),args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:1920,height:1080}});
 const errors=[],failed=[],httpErrors=[],checks=[];page.on('response',r=>{if(r.status()>=400)httpErrors.push({url:r.url(),status:r.status()})});page.on('pageerror',e=>errors.push(e.message));page.on('requestfailed',r=>failed.push(r.url()));
 function ok(name,v){checks.push({name,passed:!!v});console.log(v?'PASS':'FAIL',name)}
 await page.goto((process.env.NYAYA_TEST_URL||'http://127.0.0.1:8765/dashboard/'),{waitUntil:'networkidle'});
 ok('Five scenes in order',JSON.stringify(await page.locator('.scene').evaluateAll(es=>es.map(e=>e.id)))===JSON.stringify(['storm','intelligence','people','command','future']));
 for(const id of ['storm','intelligence','people','command','future']){
 await page.locator('#'+id).scrollIntoViewIfNeeded();await page.waitForTimeout(250);
 ok(id+' image decoded',await page.locator('#'+id+' .foundation').evaluate(e=>e.complete&&e.naturalWidth>0));
 }
 await page.locator('#sound').click();ok('Sound ON browser interaction',await page.locator('#sound').getAttribute('aria-pressed')==='true');
 await page.locator('#sound').click();ok('Sound OFF browser interaction',await page.locator('#sound').getAttribute('aria-pressed')==='false');
 await page.locator('#motion').click();ok('Motion pauses',await page.locator('body').evaluate(e=>e.classList.contains('paused')));await page.locator('#motion').click();
 await page.locator('nav a[href="#intelligence"]').click();await page.waitForTimeout(500);ok('Navigation hash',await page.evaluate(()=>location.hash==='#intelligence'));
 const toggle=page.locator('.layer-toggle').first();await toggle.click();ok('Map layer toggles off',await toggle.getAttribute('aria-pressed')==='false');await toggle.click();
 await page.locator('[data-decision="REVIEW"]').click();ok('Decision card interaction',(await page.locator('#decision-detail').innerText()).includes('escrow'));
 await page.locator('.tools .open-dashboard').click();await page.waitForTimeout(1500);ok('Dashboard dialog opens',await page.locator('#dashboard-dialog').evaluate(e=>e.open));
 const f=page.frameLocator('#dashboard-frame');await f.locator('#btn-tab-xray').waitFor();
 await page.waitForFunction(()=>document.querySelector('iframe').contentWindow.nyayaDashboardReady===true,{},{timeout:15000});ok('Dashboard initialized with recorded fixtures',true);
 for(const tab of ['replay','xray','policy','analyst']){await f.locator('#btn-tab-'+tab).click();ok('Dashboard '+tab+' tab',await f.locator('#tab-'+tab).isVisible());}
 await page.locator('#close-dashboard').click();ok('Dashboard closes',!await page.locator('#dashboard-dialog').evaluate(e=>e.open));
 await page.setViewportSize({width:390,height:844});await page.goto((process.env.NYAYA_TEST_URL||'http://127.0.0.1:8765/dashboard/'));
 for(const id of ['storm','intelligence','people','command','future']){await page.locator('#'+id).scrollIntoViewIfNeeded();await page.waitForTimeout(100);ok('Mobile '+id+' no page overflow',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));}
 ok('No uncaught JavaScript errors',errors.length===0);ok('No failed resource requests',failed.length===0);
 fs.writeFileSync('dashboard/tests/browser-results.json',JSON.stringify({checks,errors,failed,httpErrors},null,2));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});