// Local demo provisioning only. Uses public fixture credentials; tokens stay in memory.
import { chromium } from "@playwright/test";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";

const root=fileURLToPath(new URL("../../",import.meta.url));
const base="http://localhost:8080";
const cache=path.join(root,"ml-service/data/demo");
const fixture=JSON.parse(await readFile(path.join(root,"infra/demo/accounts.json"),"utf8"));
const manifest=JSON.parse(await readFile(path.join(root,"ml-service/evaluation/demo-manifest.json"),"utf8"));
const config=JSON.parse(execFileSync("docker",["compose","config","--format","json"],{cwd:root,encoding:"utf8"}));
if(config.name!=="mediamesh" || !config.services.keycloak.command.includes("start-dev"))
  throw new Error("Demo seeding requires the local development Compose stack");
const endpoint=execFileSync("docker",["compose","exec","-T","backend","printenv","AZURE_EMULATOR_ENDPOINT"],{cwd:root,encoding:"utf8"}).trim();
if(endpoint!=="http://azurite:10000/devstoreaccount1") throw new Error("Demo seeding is restricted to the local Azure Blob emulator");

// Validate files before creating users or assets.
for(const item of manifest.items){
  if(path.basename(item.filename)!==item.filename) throw new Error("Unsafe media filename");
  const bytes=await readFile(path.join(cache,item.filename));
  if(createHash("sha256").update(bytes).digest("hex")!==item.sha256)
    throw new Error(`Checksum mismatch: ${item.id}`);
  if(!item.creator || !item.license || !item.source_page) throw new Error(`Missing credits: ${item.id}`);
}

async function provider(route,options={}){
  const response=await fetch(base+"/auth"+route,{...options,signal:AbortSignal.timeout(10000)});
  if(!response.ok){
    const detail=await response.json().catch(()=>({}));
    throw new Error(`Local identity provisioning failed (${response.status}): ${detail.errorMessage || detail.error || "unknown error"}`);
  }
  return response.status===204 || response.headers.get("content-length")==="0" ? null : response.json().catch(()=>null);
}
const authentication=await provider("/realms/master/protocol/openid-connect/token",{
  method:"POST",body:new URLSearchParams({client_id:"admin-cli",grant_type:"password",username:"local-admin",password:"local-development-only"}),
});
for(const account of fixture.accounts){
  const headers={Authorization:`Bearer ${authentication.access_token}`,"Content-Type":"application/json"};
  const found=await provider(`/admin/realms/mediamesh/users?exact=true&username=${encodeURIComponent(account.username)}`,{headers});
  if(found.length){
    if(found[0].email!==account.email || found[0].lastName!==account.lastName)
      throw new Error(`Existing user does not match the demo fixture: ${account.username}`);
  }else{
    await provider("/admin/realms/mediamesh/users",{method:"POST",headers,body:JSON.stringify({
      username:account.username,firstName:account.firstName,lastName:account.lastName,email:account.email,
      enabled:true,emailVerified:true,credentials:[{type:"password",value:fixture.localDemoPassword,temporary:false}],
    })});
    console.log(`Created local account ${account.username}`);
  }
}

const browser=await chromium.launch({headless:true});
const contexts=[];
async function login(username){
  const context=await browser.newContext();contexts.push(context);
  const page=await context.newPage();
  const account={page,token:null,profile:null};
  page.on("request",request=>{if(request.url().endsWith("/api/me")) account.token=request.headers().authorization;});
  await page.goto(base,{timeout:30000});
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(fixture.localDemoPassword);
  await page.locator("#kc-login").click();
  await page.getByRole("button",{name:"Sign out"}).waitFor({timeout:30000});
  if(!account.token) throw new Error(`No authenticated API session for ${username}`);
  account.profile=await api(account,"GET","/me");
  return account;
}
async function api(account,method,route,data){
  const response=await account.page.request.fetch(base+"/api"+route,{
    method,headers:{Authorization:account.token},...(data===undefined?{}:{data}),timeout:20000,
  });
  if(!response.ok()) throw new Error(`API ${method} ${route} failed (${response.status()})`);
  return response.json();
}
const statePath=path.join(cache,"upload-state.json");
let state;
try{state=JSON.parse(await readFile(statePath,"utf8"));}catch(error){if(error.code!=="ENOENT") throw error;state={version:1,assets:{}};}
async function save(){await mkdir(cache,{recursive:true});await writeFile(statePath+".tmp",JSON.stringify(state,null,2)+"\n");await import("node:fs/promises").then(fs=>fs.rename(statePath+".tmp",statePath));}
function credit(item){
  return `${item.license}. Credit: ${item.creator}. Source: ${item.source_page}. License: ${item.license_url || item.source_page}. Curated for the MediaMesh educational demo; verify rights before publication.`;
}
const uploaded=[];
try{
  const admin=await login("admin");
  const users=new Map();
  for(const fixtureUser of fixture.accounts){
    const user=await login(fixtureUser.username);
    await api(admin,"PUT",`/admin/users/${user.profile.id}/roles`,{roles:fixtureUser.roles});
    users.set(fixtureUser.username,user);
  }
  for(const fixtureUser of fixture.accounts.filter(account=>account.domain)){
    const user=users.get(fixtureUser.username);
    const owned=[];
    for(let offset=0;;offset+=50){
      const page=await api(user,"GET",`/assets?offset=${offset}`);owned.push(...page);if(page.length<50) break;
    }
    for(const item of manifest.items.filter(item=>item.domain===fixtureUser.domain)){
      const title=`${item.domain[0].toUpperCase()+item.domain.slice(1)} | ${item.title}`.slice(0,255);
      let entry=state.assets[item.id];
      if(entry && entry.sha256!==item.sha256) throw new Error(`Seed source changed: ${item.id}; review before replacing it`);
      if(entry && entry.ownerId!==user.profile.id) entry=null;
      if(!entry){
        const existing=owned.find(asset=>asset.title===title && asset.usageNote?.includes(item.source_page));
        if(existing) entry={assetId:existing.assetId,ownerId:user.profile.id,sha256:item.sha256};
      }
      let current;
      if(entry){
        const result=await user.page.request.get(base+`/api/assets/${entry.assetId}`,{headers:{Authorization:user.token}});
        if(result.status()===404) entry=null;
        else if(!result.ok()) throw new Error(`Cannot inspect saved demo asset: ${item.id}`);
        else current=await result.json();
      }
      const contentType=item.mediaType==="video"?"video/mp4":"image/jpeg";
      if(!entry){
        const initiated=await api(user,"POST","/assets/initiate",{
          filename:item.filename,contentType,title,description:item.description || item.title,
          species:item.species || null,location:item.location || null,capturedAt:item.capturedAt || null,
          contributor:item.creator,usageNote:credit(item),
        });
        entry={assetId:initiated.assetId,ownerId:user.profile.id,sha256:item.sha256};
        state.assets[item.id]=entry;await save();
        const response=await user.page.request.put(initiated.uploadUrl,{
          headers:{...initiated.uploadHeaders,"Content-Type":contentType,"If-None-Match":"*"},
          data:await readFile(path.join(cache,item.filename)),timeout:120000,
        });
        if(!response.ok()) throw new Error(`Blob upload failed for ${item.id} (${response.status()})`);
        await api(user,"POST",`/assets/${entry.assetId}/complete`);
      }else if(current.processingStatus==="UPLOADING"){
        // A completed PUT can safely be finalized after an interrupted seed run.
        await api(user,"POST",`/assets/${entry.assetId}/complete`);
      }else if(current.processingStatus==="FAILED"){
        throw new Error(`Indexing previously failed for ${item.id}; inspect worker logs before retrying`);
      }
      state.assets[item.id]=entry;await save();uploaded.push({item,entry,user});
      console.log(`${fixtureUser.username}: ${item.id}`);
    }
  }
  const deadline=Date.now()+1800000;
  let pending=[...uploaded];
  while(pending.length){
    const remaining=[];
    for(const asset of pending){
      const current=await api(asset.user,"GET",`/assets/${asset.entry.assetId}`);
      if(current.processingStatus==="FAILED") throw new Error(`Indexing failed: ${asset.item.id}`);
      if(current.processingStatus!=="READY") remaining.push(asset);
    }
    console.log(`READY ${uploaded.length-remaining.length}/${uploaded.length}`);
    pending=remaining;
    if(pending.length){if(Date.now()>deadline) throw new Error("Indexing did not finish; rerun to resume");await new Promise(resolve=>setTimeout(resolve,2000));}
  }
  // READY alone is insufficient after changing models or enabling descriptions.
  // Explicit IDs keep unrelated user uploads outside this resumable backfill.
  execFileSync("docker",["compose","run","--rm","--no-deps","-T","ml-worker",
    "python","-u","-m","mediamesh_ml.seed_enrich"],{
    cwd:root,input:JSON.stringify(uploaded.map(asset=>asset.entry.assetId)),
    stdio:["pipe","inherit","inherit"],timeout:3600000,
  });
  for(const asset of uploaded){
    const current=await api(asset.user,"GET",`/assets/${asset.entry.assetId}`);
    if(!current.generatedDescription?.trim()) throw new Error(`Missing visual description: ${asset.item.id}`);
  }
  const researcher=users.get("demo.researcher");
  for(const fixtureUser of fixture.accounts.filter(account=>account.domain)){
    const user=users.get(fixtureUser.username);
    const assets=await api(user,"GET","/assets");
    const expected=uploaded.filter(asset=>asset.user===user);
    if(assets.length!==expected.length || assets.some(asset=>asset.ownerId!==user.profile.id))
      throw new Error(`Unexpected catalog ownership or duplicates for ${fixtureUser.username}`);
    await user.page.reload();
    await user.page.getByRole("heading",{name:"Contribute to the archive"}).waitFor();
    await user.page.locator(".asset-row").last().waitFor();
    if(await user.page.locator(".asset-row").count()!==expected.length)
      throw new Error(`Uploader UI is missing demo assets: ${fixtureUser.username}`);
  }
  const plants=users.get("demo.plants");
  const crossOwner=await plants.page.request.get(base+`/api/assets/${uploaded[0].entry.assetId}`,{headers:{Authorization:plants.token}});
  if(![403,404].includes(crossOwner.status())) throw new Error("Uploader ownership isolation failed");
  const deniedSearch=await plants.page.request.post(base+"/api/search",{headers:{Authorization:plants.token},data:{query:"flowers"}});
  if(deniedSearch.status()!==403) throw new Error("Uploader unexpectedly has researcher access");
  const queries=["elephants drinking at a watering hole","yellow sunflower","ocean waves","sea turtle underwater","a puffin bird","a waterfall surrounded by green rainforest"];
  const searchChecks=[];
  for(const query of queries){
    const response=await api(researcher,"POST","/search",{query,limit:10});
    searchChecks.push({query,results:response.results.map(result=>({assetId:result.assetId,title:result.title,score:result.score}))});
    if(!response.results.length) throw new Error("Expected searchable demo media");
  }
  const sample=uploaded[0];
  const access=await api(researcher,"POST",`/assets/${sample.entry.assetId}/access-url`);
  const preview=await researcher.page.request.get(access.url,{timeout:15000});
  if(!preview.ok()) throw new Error("Signed preview failed");
  await researcher.page.reload();
  await researcher.page.getByLabel("Describe what you need").fill("yellow sunflower");
  await researcher.page.getByRole("button",{name:"Search archive"}).click();
  const flower=researcher.page.locator(".result").filter({hasText:"Sunflower head"});
  await flower.getByRole("button",{name:"Preview",exact:true}).click();
  const image=researcher.page.getByRole("dialog",{name:"Media preview"}).getByRole("img");
  await image.waitFor();
  await image.evaluate(img=>img.decode());
  if(await image.evaluate(img=>img.naturalWidth)<=0) throw new Error("Demo preview did not render");
  const report={seededAt:new Date().toISOString(),ready:uploaded.length,accounts:fixture.accounts.map(a=>({username:a.username,domain:a.domain,roles:a.roles})),domains:Object.fromEntries(fixture.accounts.filter(a=>a.domain).map(a=>[a.domain,uploaded.filter(x=>x.item.domain===a.domain).length])),searchChecks};
  await writeFile(path.join(cache,"seed-report.json"),JSON.stringify(report,null,2)+"\n");
  console.log(JSON.stringify({ready:report.ready,domains:report.domains},null,2));
}finally{
  await Promise.all(contexts.map(context=>context.close()));await browser.close();
}
