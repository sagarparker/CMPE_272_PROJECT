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
  const materials=new Map(),layers=[],foliage=[],eyes=[],swayingTrees=[],driftingLeaves=[];let drawOrder=0;
  function material(color){if(!materials.has(color))materials.set(color,new THREE.MeshBasicMaterial({color,side:THREE.DoubleSide}));return materials.get(color);}
  function layer(z,speed){const g=new THREE.Group();g.position.z=z;scene.add(g);layers.push({g,speed});return g;}
  function shape(parent,color,draw){const p=new THREE.Shape();draw(p);const m=new THREE.Mesh(new THREE.ShapeGeometry(p,24),material(color));m.renderOrder=drawOrder++;parent.add(m);return m;}
  function oval(parent,color,x,y,rx,ry){const p=new THREE.Shape();p.absellipse(0,0,rx,ry,0,Math.PI*2,false,0);const m=shape(parent,color,s=>s.copy(p));m.position.set(x,y,0);return m;}
  function polygon(parent,color,points){return shape(parent,color,p=>{p.moveTo(...points[0]);points.slice(1).forEach(v=>p.lineTo(...v));p.closePath();});}
  function line(parent,color,points,width=.035){const path=new THREE.CatmullRomCurve3(points.map(([x,y])=>new THREE.Vector3(x,y,.015)));const m=new THREE.Mesh(new THREE.TubeGeometry(path,24,width,5,false),material(color));m.renderOrder=drawOrder++;parent.add(m);return m;}
  function leaf(parent,color,x,y,length,angle){const g=new THREE.Group();g.position.set(x,y,.02);g.rotation.z=angle;parent.add(g);shape(g,color,p=>{p.moveTo(0,0);p.bezierCurveTo(-length*.5,length*.35,-length*.28,length*.84,0,length);p.bezierCurveTo(length*.3,length*.78,length*.4,length*.3,0,0);});line(g,0x81a076,[[0,0],[0,length*.85]],.012);foliage.push({g,angle,phase:x+y});return g;}
  function sprig(parent,stemColor,points,count,length,colors,thickness=.035){
   line(parent,stemColor,points,thickness);
   const curve=new THREE.CatmullRomCurve3(points.map(([x,y])=>new THREE.Vector3(x,y,0)));
   for(let i=0;i<count;i++){
    const t=.3+i*.62/Math.max(1,count-1),point=curve.getPoint(t),tangent=curve.getTangent(t);
    const direction=Math.atan2(-tangent.x,tangent.y);
    leaf(parent,colors[i%colors.length],point.x,point.y,length*(1-t*.35),direction+(i%2===0?.8:-.8));
   }
  }
  // Flat, overlapping silhouettes preserve the original bird-and-canopy composition.
  const sky=layer(-8,.08);
  const far=layer(-5,.16);
  for(let i=0;i<9;i++){
   const x=-6+i*1.55,tree=new THREE.Group();tree.position.set(x,-3,0);far.add(tree);
   polygon(tree,0x7e9270,[[-.11,0],[.12,0],[.25,7],[.06,7]]);
   oval(tree,[0x91a47c,0x879e75,0x7f986f][i%3],0,5.1+(i%3)*.65,1.8,2.1);
   swayingTrees.push({g:tree,phase:i*.85,amount:.022,speed:.55});
  }
  const trees=layer(-3,.3);
  let treeIndex=0;
  for(const [x,y,r]of[[-4.5,2.6,1.8],[-2.5,3.8,1.65],[.9,4.4,1.9],[4.6,2.8,2]]){
   const tree=new THREE.Group();tree.position.set(x,-3.5,0);trees.add(tree);
   polygon(tree,0x777e4e,[[-.14,0],[.14,0],[.3,y+3.5],[.07,y+3.5]]);
   oval(tree,0x617e55,0,y+3.5,r,r*.83);
   oval(tree,0x6c895a,-.35,y+3.75,r*.83,r*.7);
   swayingTrees.push({g:tree,phase:treeIndex++*1.1,amount:.035,speed:.65});
  }
  const middle=layer(-1,.45);
  oval(middle,0x688657,.1,.9,2.25,1.6);
  oval(middle,0x76935e,-.25,1.25,2,1.25);
  shape(middle,0x557750,p=>{p.moveTo(-10,-6);p.lineTo(-10,-2);p.bezierCurveTo(-5,-1.2,1,-1.6,10,-2.3);p.lineTo(10,-6);p.closePath();});
  const perch=layer(1,.6);
  // The foreground trunk is a separate page layer so it can overlap the sign-in panel.
  // Thick at the trunk, tapering to a point; the bird's feet meet its upper edge.
  shape(perch,0x605137,p=>{p.moveTo(-4.8,-1.86);p.quadraticCurveTo(-1.8,-1.54,.65,-1.22);p.quadraticCurveTo(3.2,-.98,6.4,-.72);p.lineTo(6.4,-1.24);p.quadraticCurveTo(2.3,-1.53,.65,-1.54);p.quadraticCurveTo(-2.4,-1.82,-4.8,-1.86);p.closePath();});
  line(perch,0x8a7950,[[-4.45,-1.83],[-1.5,-1.48],[.65,-1.24],[3.55,-.95],[6.13,-.78]],.018);
  sprig(perch,0x605137,[[2.05,-1.16],[2.7,-.76],[3.1,-.15]],3,.65,[0x4a714b,0x5c7e50]);
  line(perch,0x766344,[[-3.4,-1.86],[-2.7,-1.77],[-2.15,-1.69]],.015);
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
  function render(){renderer.render(scene,camera);}
  // Sample the actual upper edge of the perch for each twig's attachment.
  // Inset the root into the wood, and keep every twig in the perch's layer.
  const leftRoot=new THREE.QuadraticBezierCurve3(new THREE.Vector3(-4.8,-1.86,0),new THREE.Vector3(-1.8,-1.54,0),new THREE.Vector3(.65,-1.22,0)).getPoint(.3);
  const rightRoot=new THREE.QuadraticBezierCurve3(new THREE.Vector3(.65,-1.22,0),new THREE.Vector3(3.2,-.98,0),new THREE.Vector3(6.4,-.72,0)).getPoint(.65);
  sprig(perch,0x605137,[[leftRoot.x,leftRoot.y-.07],[leftRoot.x-.45,leftRoot.y+.55],[leftRoot.x-.95,leftRoot.y+1.5]],4,1.2,[0x305a3d,0x3f6846,0x4f7750],.055);
  sprig(perch,0x605137,[[rightRoot.x,rightRoot.y-.07],[rightRoot.x+.35,rightRoot.y+.6],[rightRoot.x+.7,rightRoot.y+1.4]],4,1.15,[0x305a3d,0x3f6846,0x4f7750],.055);
  const lowerLeft=new THREE.QuadraticBezierCurve3(new THREE.Vector3(.65,-1.54,0),new THREE.Vector3(-2.4,-1.82,0),new THREE.Vector3(-4.8,-1.86,0)).getPoint(.45);
  const lowerRight=new THREE.QuadraticBezierCurve3(new THREE.Vector3(.65,-1.54,0),new THREE.Vector3(2.3,-1.53,0),new THREE.Vector3(6.4,-1.24,0)).getPoint(.55);
  sprig(perch,0x605137,[[lowerLeft.x,lowerLeft.y+.06],[lowerLeft.x-.35,lowerLeft.y-.45],[lowerLeft.x-.7,lowerLeft.y-1]],4,.8,[0x305a3d,0x3f6846,0x4f7750],.045);
  sprig(perch,0x605137,[[lowerRight.x,lowerRight.y+.06],[lowerRight.x+.55,lowerRight.y-.5],[lowerRight.x+1,lowerRight.y-1.35]],4,.85,[0x305a3d,0x3f6846,0x4f7750],.045);
  // Drifting leaf silhouettes make the breeze visible even without pointer movement.
  const breeze=layer(3,.7);
  for(let i=0;i<12;i++){
   const g=new THREE.Group(),x=Math.sin(i*7.1)*5.5,y=(i*.91)%10-4;
   const size=.04+(i%3)*.018;
   polygon(g,[0xa3af76,0x829765,0xc1bb7d][i%3],[[0,-size],[size*.6,0],[0,size],[-size*.6,0]]);
   g.position.set(x,y,0);breeze.add(g);driftingLeaves.push({g,x,y,speed:.13+(i%4)*.04,phase:i*1.7});
  }
  const birdMotion=new THREE.Group();birdMotion.position.set(.65,-1.22,.05);perch.add(birdMotion);birdMotion.add(bird);bird.position.set(0,1.1,0);
  stage.prepend(renderer.domElement);stage.classList.add('has-webgl');stage.dataset.renderer='threejs-layered';
  let frame=0,last=0,time=0,pointer=0,paused=motion.matches;const toggle=document.querySelector('[data-motion-toggle]');
  function label(){if(toggle){toggle.textContent=paused?'Play animation':'Pause animation';toggle.setAttribute('aria-pressed',String(paused));}}label();
  function resize(){const r=stage.getBoundingClientRect();if(!r.width||!r.height)return;camera.left=-6*r.width/r.height;camera.right=6*r.width/r.height;camera.updateProjectionMatrix();renderer.setSize(r.width,r.height);render();}
  const observer=new ResizeObserver(resize);observer.observe(stage);resize();
  function animate(now){
   frame=0;if(document.hidden||paused)return;
   if(now-last>1000/30){
    time+=Math.min((now-last)/1000,.05);last=now;
    for(const l of layers){const target=pointer*l.speed*.22+Math.sin(time*.3+l.speed)*l.speed*.045;l.g.position.x+=(target-l.g.position.x)*.035;}
    for(const tree of swayingTrees)tree.g.rotation.z=Math.sin(time*tree.speed+tree.phase)*tree.amount+Math.sin(time*.27+tree.phase)*.009;
    for(const item of foliage)item.g.rotation.z=item.angle+Math.sin(time*.95+item.phase)*.085+Math.sin(time*1.7+item.phase)*.025;
    birdMotion.rotation.z=Math.sin(time*.8)*.018+Math.sin(time*.31)*.009;
    for(const item of driftingLeaves){item.g.position.y=5-((5-item.y+time*item.speed)%10);item.g.position.x=item.x+Math.sin(time*.6+item.phase)*.4;item.g.rotation.z=time*.45+item.phase;item.g.scale.x=.65+Math.sin(time+item.phase)*.3;}
    for(const eye of eyes){const blink=Math.sin(time*1.05+eye.phase)>.995;eye.e.scale.y=blink?.15:1;}
    render();
   }
   frame=requestAnimationFrame(animate);
  }
  function start(){if(frame)cancelAnimationFrame(frame);frame=0;if(!document.hidden&&!paused)frame=requestAnimationFrame(animate);else render();}
  stage.addEventListener('pointermove',e=>{const r=stage.getBoundingClientRect();pointer=(e.clientX-r.left)/r.width-.5;});stage.addEventListener('pointerleave',()=>{pointer=0;});
  document.addEventListener('visibilitychange',start);motion.addEventListener('change',()=>{paused=motion.matches;label();start();});toggle?.addEventListener('click',()=>{paused=!paused;label();start();});start();
  renderer.domElement.addEventListener('webglcontextlost',()=>{paused=true;stage.classList.remove('has-webgl');stage.dataset.renderer='fallback';if(toggle)toggle.hidden=true;});
  addEventListener('pagehide',()=>{cancelAnimationFrame(frame);observer.disconnect();scene.traverse(o=>o.geometry?.dispose());materials.forEach(m=>m.dispose());renderer.dispose();},{once:true});
 }
}
