/* Original procedural audio: no external recordings, samples, network calls or licences required.
 * Stylized approximations; not authentic field recordings. One context, scene bus crossfades,
 * bounded one-shots and visibility suspension. Audio starts ONLY on an explicit gesture. */
(() => {
'use strict';
class NyayaAudio {
 constructor(){this.ctx=null;this.enabled=false;this.volume=.35;this.scene=0;this.buses=[];this.sources=[];this.timer=null;this.ducked=false;this.disposed=false;}
 init(){
  const Context=window.AudioContext||window.webkitAudioContext;
  if(!Context) throw new Error('Web Audio is unavailable in this browser.');
  this.ctx=new Context();const c=this.ctx;
  this.master=c.createGain();this.master.gain.value=0;
  const limiter=c.createDynamicsCompressor();limiter.threshold.value=-18;limiter.ratio.value=8;
  this.master.connect(limiter);limiter.connect(c.destination);
  this.noise=c.createBuffer(1,c.sampleRate*4,c.sampleRate);const data=this.noise.getChannelData(0);
  let brown=0;for(let i=0;i<data.length;i++){brown=(brown+(Math.random()*2-1)*.025)/1.025;data[i]=brown*4;}
  for(let i=0;i<5;i++){const g=c.createGain();g.gain.value=0;g.connect(this.master);this.buses.push(g);}
  // Rain, wind and ocean; rotor, distant siren; quiet human-scene air; machine-room hum; finale chord.
  this.bed(0,1800,.32,'highpass',.08);this.bed(0,320,.45,'lowpass',.11);this.bed(0,900,.22,'lowpass',.2);
  this.tone(0,54,.045,'triangle',18,30);this.tone(0,620,.006,'sine',.21,130);
  this.bed(1,270,.5,'lowpass',.1);this.tone(1,82,.025,'sine',.12,3);
  this.bed(2,1400,.2,'highpass',.1);this.bed(2,650,.22,'lowpass',.22);this.tone(2,540,.003,'sine',.17,100);
  this.bed(3,220,.12,'lowpass',.1);this.tone(3,65.4,.03,'sine',.06,1);
  this.bed(4,500,.12,'lowpass',.07);[130.81,164.81,196,261.63].forEach(f=>this.tone(4,f,.018,'sine',.06,.7));
  this.timer=setInterval(()=>this.tick(),1300);
 }
 bed(scene,frequency,level,type,rate){const c=this.ctx,s=c.createBufferSource(),f=c.createBiquadFilter(),g=c.createGain();s.buffer=this.noise;s.loop=true;f.type=type;f.frequency.value=frequency;g.gain.value=level;s.connect(f);f.connect(g);g.connect(this.buses[scene]);s.start();this.sources.push(s);const l=c.createOscillator(),a=c.createGain();l.frequency.value=rate;a.gain.value=level*.25;l.connect(a);a.connect(g.gain);l.start();this.sources.push(l);}
 tone(scene,freq,level,type,rate,depth){const c=this.ctx,s=c.createOscillator(),g=c.createGain();s.type=type;s.frequency.value=freq;g.gain.value=level;s.connect(g);g.connect(this.buses[scene]);s.start();this.sources.push(s);const l=c.createOscillator(),a=c.createGain();l.frequency.value=rate;a.gain.value=depth;l.connect(a);a.connect(s.frequency);l.start();this.sources.push(l);}
 async toggle(){if(this.disposed)return false;if(!this.ctx)this.init();if(!this.enabled){await this.ctx.resume();this.enabled=true;this.setScene(this.scene);this.updateMaster();}else{this.enabled=false;this.master.gain.cancelScheduledValues(this.ctx.currentTime);this.master.gain.setValueAtTime(0,this.ctx.currentTime);}return this.enabled;}
 updateMaster(){if(!this.ctx)return;const t=this.ctx.currentTime;this.master.gain.cancelScheduledValues(t);this.master.gain.setTargetAtTime(this.enabled?this.volume*(this.ducked?.12:1):0,t,.12);}
 setVolume(v){this.volume=Math.max(0,Math.min(1,v));this.updateMaster();}
 duck(v){this.ducked=v;this.updateMaster();}
 setScene(scene){this.scene=scene;if(!this.ctx)return;this.buses.forEach((g,i)=>{const t=this.ctx.currentTime;g.gain.cancelScheduledValues(t);g.gain.setTargetAtTime(i===scene?1:0,t,.7);});}
 oneShot({noise=false,freq=440,duration=.15,level=.05,delay=0,scene=this.scene,type='sine'}={}){
  if(!this.enabled||!this.ctx||this.ctx.state!=='running')return;const c=this.ctx,t=c.currentTime+delay,s=noise?c.createBufferSource():c.createOscillator(),g=c.createGain(),f=c.createBiquadFilter();
  if(noise){s.buffer=this.noise;f.type='lowpass';f.frequency.value=freq;}else{s.type=type;s.frequency.value=freq;f.type='lowpass';f.frequency.value=4000;}
  s.connect(f);f.connect(g);g.connect(this.buses[scene]);g.gain.setValueAtTime(0,t);g.gain.linearRampToValueAtTime(level,t+.015);g.gain.exponentialRampToValueAtTime(.0001,t+duration);s.start(t);s.stop(t+duration+.03);s.onended=()=>{s.disconnect();f.disconnect();g.disconnect();};
 }
 thunder(){this.oneShot({noise:true,freq:220,duration:2.6,level:.55,delay:.45,scene:0});}
 click(){this.oneShot({noise:true,freq:2400,duration:.055,level:.06});}
 tick(){if(!this.enabled||document.hidden)return;if(this.scene===1)this.oneShot({freq:720,duration:.55,level:.025});if(this.scene===2){this.oneShot({noise:true,freq:350,duration:.13,level:.055});this.oneShot({noise:true,freq:280,duration:.15,level:.04,delay:.36});}if(this.scene===3){this.oneShot({noise:true,freq:1800,duration:.045,level:.06});this.oneShot({noise:true,freq:2100,duration:.04,level:.04,delay:.17});if(Math.random()<.2)this.oneShot({freq:880,duration:.3,level:.018});}}
 async visibility(){if(!this.ctx)return;if(document.hidden)await this.ctx.suspend();else if(this.enabled)await this.ctx.resume();}
 dispose(){this.disposed=true;clearInterval(this.timer);this.sources.forEach(s=>{try{s.stop();s.disconnect();}catch{}});if(this.ctx)this.ctx.close();}
}
window.NyayaAudio=NyayaAudio;
})();
