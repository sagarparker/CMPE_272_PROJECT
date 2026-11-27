import * as THREE from 'three';

const authPage=document.querySelector('[data-auth-checker]');
if(authPage?.dataset.authPolling) import(/* @vite-ignore */ authPage.dataset.authChecker).then(module=>module.startSessionPolling(authPage.dataset.authPolling)).catch(()=>{});
const stage=document.querySelector('[data-jungle-scene]');
if(stage){
 const motion=matchMedia('(prefers-reduced-motion: reduce)');let renderer;
 try{renderer=new THREE.WebGLRenderer({antialias:true,alpha:true,powerPreference:'low-power'});}catch{stage.dataset.renderer='fallback';const b=document.querySelector('[data-motion-toggle]');if(b)b.hidden=true;}
 if(renderer){
  renderer.setPixelRatio(Math.min(devicePixelRatio,1.5));renderer.setClearColor(0,0);renderer.outputColorSpace=THREE.SRGBColorSpace;
  const scene=new THREE.Scene(),camera=new THREE.OrthographicCamera(-5,5,6,-6,.1,60);camera.position.z=30;
  const materials=new Map(),layers=[],foliage=[],eyes=[];let drawOrder=0;
  function material(color){if(!materials.has(color))materials.set(color,new THREE.MeshBasicMaterial({color,side:THREE.DoubleSide}));return materials.get(color);}
  function layer(z,speed){const g=new THREE.Group();g.position.z=z;scene.add(g);layers.push({g,speed});return g;}
  function shape(parent,color,draw){const p=new THREE.Shape();draw(p);const m=new THREE.Mesh(new THREE.ShapeGeometry(p,24),material(color));m.renderOrder=drawOrder++;parent.add(m);return m;}
  function oval(parent,color,x,y,rx,ry){const p=new THREE.Shape();p.absellipse(0,0,rx,ry,0,Math.PI*2,false,0);const m=shape(parent,color,s=>s.copy(p));m.position.set(x,y,0);return m;}
  function polygon(parent,color,points){return shape(parent,color,p=>{p.moveTo(...points[0]);points.slice(1).forEach(v=>p.lineTo(...v));p.closePath();});}
  function line(parent,color,points,width=.035){const path=new THREE.CatmullRomCurve3(points.map(([x,y])=>new THREE.Vector3(x,y,.015)));const m=new THREE.Mesh(new THREE.TubeGeometry(path,24,width,5,false),material(color));m.renderOrder=drawOrder++;parent.add(m);return m;}
  function leaf(parent,color,x,y,length,angle){const g=new THREE.Group();g.position.set(x,y,.02);g.rotation.z=angle;parent.add(g);shape(g,color,p=>{p.moveTo(0,0);p.bezierCurveTo(-length*.5,length*.35,-length*.28,length*.84,0,length);p.bezierCurveTo(length*.3,length*.78,length*.4,length*.3,0,0);});line(g,0x81a076,[[0,0],[0,length*.85]],.012);foliage.push({g,angle,phase:x+y});return g;}
  // Flat, overlapping silhouettes preserve the original bird-and-canopy composition.
  const sky=layer(-8,.08);
  const far=layer(-5,.16);
  for(let i=0;i<9;i++){
   const x=-6+i*1.55;
   polygon(far,0x7e9270,[[x-.11,-3],[x+.12,-3],[x+.25,4],[x+.06,4]]);
   oval(far,[0x91a47c,0x879e75,0x7f986f][i%3],x,2.1+(i%3)*.65,1.8,2.1);
  }
  const trees=layer(-3,.3);
  for(const [x,y,r]of[[-4.5,2.6,1.8],[-2.5,3.8,1.65],[.9,4.4,1.9],[4.6,2.8,2]]){
   polygon(trees,0x777e4e,[[x-.14,-3.5],[x+.14,-3.5],[x+.3,y],[x+.07,y]]);
   oval(trees,0x617e55,x,y,r,r*.83);
   oval(trees,0x6c895a,x-.35,y+.25,r*.83,r*.7);
  }
  const middle=layer(-1,.45);
  oval(middle,0x688657,.1,.9,2.25,1.6);
  oval(middle,0x76935e,-.25,1.25,2,1.25);
  shape(middle,0x557750,p=>{p.moveTo(-10,-6);p.lineTo(-10,-2);p.bezierCurveTo(-5,-1.2,1,-1.6,10,-2.3);p.lineTo(10,-6);p.closePath();});
  const perch=layer(1,.6);
  // The top edge is also the feet's contact line: y = -1.22 + .1 * (x - .65).
  shape(perch,0x605137,p=>{p.moveTo(-5,-1.785);p.quadraticCurveTo(-1,-1.43,3.65,-.92);p.lineTo(3.65,-1.14);p.quadraticCurveTo(-1,-1.72,-5,-2.1);p.closePath();});
  line(perch,0x8a7950,[[-4.9,-1.82],[-1.5,-1.48],[.65,-1.24],[3.55,-.95]],.023);
  line(perch,0x605137,[[2.05,-1.16],[2.7,-.76],[3.1,-.15]],.075);
  line(perch,0x766344,[[-3.4,-1.86],[-2.7,-1.77],[-2.15,-1.69]],.015);
  leaf(perch,0x4a714b,2.79,-.6,.58,-.8);
  leaf(perch,0x5c7e50,3.02,-.3,.48,.5);
  const bird=new THREE.Group();bird.position.set(.65,-.12,.05);perch.add(bird);
  // Preserve the original silhouette; use restrained contrast to define its features.
  polygon(bird,0x203c30,[[-.52,-.52],[-.58,-1.52],[-.14,-1.2],[.02,-.48]]);
  line(bird,0x3e6246,[[-.38,-.87],[-.43,-1.28]],.018);
  oval(bird,0x203c2e,-.14,-.12,.62,.89);
  shape(bird,0x3b6043,p=>{p.moveTo(-.54,.35);p.bezierCurveTo(-.94,.02,-.7,-.61,-.39,-.76);p.bezierCurveTo(-.14,-.54,-.07,-.08,-.23,.2);p.closePath();});
  line(bird,0x182f25,[[-.54,.35],[-.23,.2],[-.2,-.2],[-.39,-.76]],.018);
  line(bird,0x58774f,[[-.53,-.12],[-.48,-.38],[-.39,-.53]],.014);
  line(bird,0x58774f,[[-.63,-.18],[-.59,-.4],[-.5,-.55]],.012);
  oval(bird,0x203c2e,.01,.75,.57,.62);
  shape(bird,0xe1dbb0,p=>{p.moveTo(-.42,.5);p.bezierCurveTo(-.64,-.09,-.3,-.5,.17,-.3);p.bezierCurveTo(.45,-.1,.35,.32,.18,.52);p.closePath();});
  shape(bird,0xd5af4d,p=>{p.moveTo(.33,.98);p.bezierCurveTo(.85,1.11,1.74,1.08,1.79,.79);p.bezierCurveTo(1.7,.52,.92,.45,.33,.58);p.closePath();});
  shape(bird,0xb88539,p=>{p.moveTo(1.41,1.02);p.bezierCurveTo(1.72,.99,1.9,.84,1.74,.65);p.lineTo(1.35,.57);p.quadraticCurveTo(1.58,.79,1.41,1.02);p.closePath();});
  line(bird,0x866335,[[.4,.65],[.96,.67],[1.57,.75]],.017);
  line(bird,0xe6c574,[[.48,1.0],[.9,1.025],[1.28,1.0]],.012);
  oval(bird,0x96753e,.49,.88,.023,.014);
  oval(bird,0xd7d4a6,.2,.88,.18,.23);
  const eye=oval(bird,0x172e25,.25,.89,.075,.105);eyes.push({e:eye,phase:0});
  oval(bird,0xf5f0d6,.275,.925,.022,.027);
  // Ankles and curled toes share the branch's slope, with the tail hanging behind.
  for(const x of [-.36,.15]){
   const contact=-1.1+.1*x;
   line(bird,0xb4a06a,[[x,-.87],[x-.025,contact+.04],[x+.04,contact]],.038);
   for(const dx of [-.045,.045,.12])line(bird,0xb4a06a,[[x-.02,contact+.055],[x+dx+.05,contact+.04],[x+dx+.08,contact-.025],[x+dx+.055,contact-.09]],.024);
   line(bird,0x6f6548,[[x-.015,contact+.015],[x-.12,contact-.03],[x-.11,contact-.09]],.022);
  }
  const foreground=layer(5,.8);
  for(const side of [-1,1]){
   line(foreground,0x3d6344,[[side*4.8,-3.4],[side*3.8,-1.6],[side*3.5,-.6]],.05);
   for(let i=0;i<5;i++)leaf(foreground,[0x305a3d,0x3f6846,0x4f7750][i%3],side*(4.8-i*.33),-3.1+i*.35,1.5,side*(.55+i*.22));
   for(let i=0;i<4;i++)leaf(foreground,[0x60834f,0x507747][i%2],side*4.5,3,1.7,side*(1.1+i*.6));
  }
  stage.prepend(renderer.domElement);stage.classList.add('has-webgl');stage.dataset.renderer='threejs-layered';
  let frame=0,last=0,time=0,pointer=0,paused=motion.matches;const toggle=document.querySelector('[data-motion-toggle]');
  function label(){if(toggle){toggle.textContent=paused?'Play animation':'Pause animation';toggle.setAttribute('aria-pressed',String(paused));}}label();
  function resize(){const r=stage.getBoundingClientRect();if(!r.width||!r.height)return;camera.left=-6*r.width/r.height;camera.right=6*r.width/r.height;camera.updateProjectionMatrix();renderer.setSize(r.width,r.height);renderer.render(scene,camera);}
  const observer=new ResizeObserver(resize);observer.observe(stage);resize();
  function animate(now){frame=0;if(document.hidden||paused)return;if(now-last>1000/30){time+=Math.min((now-last)/1000,.05);last=now;for(const l of layers)l.g.position.x+=(pointer*l.speed*.15-l.g.position.x)*.025;for(const item of foliage)item.g.rotation.z=item.angle+Math.sin(time*.45+item.phase)*.012;for(const eye of eyes){const blink=Math.sin(time*.55+eye.phase)>.998;eye.e.scale.y=blink?.15:1;}renderer.render(scene,camera);}frame=requestAnimationFrame(animate);}
  function start(){if(frame)cancelAnimationFrame(frame);frame=0;if(!document.hidden&&!paused)frame=requestAnimationFrame(animate);else renderer.render(scene,camera);}
  stage.addEventListener('pointermove',e=>{const r=stage.getBoundingClientRect();pointer=(e.clientX-r.left)/r.width-.5;});stage.addEventListener('pointerleave',()=>{pointer=0;});
  document.addEventListener('visibilitychange',start);motion.addEventListener('change',()=>{paused=motion.matches;label();start();});toggle?.addEventListener('click',()=>{paused=!paused;label();start();});start();
  renderer.domElement.addEventListener('webglcontextlost',()=>{paused=true;stage.classList.remove('has-webgl');stage.dataset.renderer='fallback';if(toggle)toggle.hidden=true;});
  addEventListener('pagehide',()=>{cancelAnimationFrame(frame);observer.disconnect();scene.traverse(o=>o.geometry?.dispose());materials.forEach(m=>m.dispose());renderer.dispose();},{once:true});
 }
}
