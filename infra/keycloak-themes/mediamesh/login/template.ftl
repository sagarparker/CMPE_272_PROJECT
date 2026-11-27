<#macro username>
  <p class="auth-account">${auth.attemptedUsername!''}</p>
</#macro>
<#macro registrationLayout bodyClass="" displayInfo=false displayMessage=true displayRequiredFields=false>
<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="robots" content="noindex, nofollow" />
  <title>Sign in | MediaMesh</title>
  <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
  <link rel="stylesheet" href="/theme.css" />
  <link rel="stylesheet" href="${url.resourcesPath}/css/login.css" />
  <script type="importmap">{"imports":{"rfc4648":"${url.resourcesCommonPath}/vendor/rfc4648/rfc4648.js"}}</script>
  <#if properties.scripts?has_content><#list properties.scripts?split(' ') as script><script src="${url.resourcesPath}/${script}"></script></#list></#if>
  <#if scripts??><#list scripts as script><script src="${script}"></script></#list></#if>
  <script type="module" src="${url.resourcesPath}/js/passwordVisibility.js"></script>
  <script type="module" src="/assets/login-jungle.js"></script>
</head>
<body class="auth-page ${bodyClass}" data-auth-checker="${url.resourcesPath}/js/authChecker.js" data-auth-polling="${url.ssoLoginInOtherTabsUrl!''}">
  <main class="auth-shell">
    <aside class="auth-illustration" aria-label="Layered forest illustration with a bird perched on a branch">
      <div class="jungle-scene" data-jungle-scene aria-hidden="true">
        <img class="scene-fallback" src="/jungle-fallback.svg" alt="" />
      </div>
      <a class="auth-brand" href="/"><span class="auth-brand-mark"></span><span>MediaMesh<span class="auth-brand-sub">EDITORIAL ARCHIVE</span></span></a>
      <div class="illustration-caption"><span class="auth-eyebrow">A WORLD WORTH DOCUMENTING</span><h1>Every perspective.<br />One shared archive.</h1><p>A workspace for the people behind the stories.</p></div>
      <button class="scene-motion" type="button" data-motion-toggle aria-pressed="false">Pause animation</button>
    </aside>
    <section class="auth-form-panel" aria-label="Account sign-in">
      <div class="auth-panel-top"><span>YOUR ORGANIZATION’S WORKSPACE</span><span class="auth-status">Member access</span></div>
      <div class="auth-card">
        <p class="auth-eyebrow">WELCOME TO MEDIAMESH</p>
        <h2 id="kc-page-title"><#nested "header"></h2>
        <p class="auth-intro">Sign in to access your editorial workspace.</p>
        <#if displayMessage && message?has_content && (message.type != 'warning' || !isAppInitiatedAction??)>
          <div class="auth-message ${message.type}" role="alert">${kcSanitize(message.summary)?no_esc}</div>
        </#if>
        <#if displayRequiredFields><p class="auth-required">* Required fields</p></#if>
        <#nested "form">
        <#nested "socialProviders">
        <#if displayInfo><div class="auth-info"><#nested "info"></div></#if>
      </div>
      <div class="auth-panel-footer"><span>MediaMesh · Editorial archive</span><span>Contact your administrator for access.</span></div>
    </section>
  </main>
</body>
</html>
</#macro>
