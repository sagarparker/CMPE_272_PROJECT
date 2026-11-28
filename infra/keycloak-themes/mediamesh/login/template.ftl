<#macro username>
  <p class="auth-account">${auth.attemptedUsername!''}</p>
</#macro>
<#macro registrationLayout bodyClass="" displayInfo=false displayMessage=true displayRequiredFields=false googleOnly=false>
<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="robots" content="noindex, nofollow" />
  <title>Sign in | MediaMesh</title>
  <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
  <link rel="stylesheet" href="/theme.css" />
  <link rel="stylesheet" href="${url.resourcesPath}/css/login.css?v=connected-stems-1" />
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
      <div class="illustration-caption"><h1>Every perspective.<br />One shared archive.</h1><p>A workspace for the people behind the stories.</p></div>
    </aside>
    <svg class="auth-tree-trunk" viewBox="0 0 120 1000" preserveAspectRatio="none" aria-hidden="true" focusable="false">
      <defs><linearGradient id="trunk-shade" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#655a3c"/><stop offset=".55" stop-color="#5c5639"/><stop offset="1" stop-color="#304b34"/></linearGradient><linearGradient id="trunk-light" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#7a6b47"/><stop offset="1" stop-color="#3c5439"/></linearGradient></defs>
      <path d="M15 1020C38 800 14 610 32 365C43 205 40 85 24-20H105C126 180 82 425 91 655C96 810 100 910 119 1020Z" fill="url(#trunk-shade)"/>
      <path d="M29 1020C50 775 29 585 46 365C56 193 54 85 39-20H54C70 185 56 360 52 510C45 740 58 870 47 1020Z" fill="url(#trunk-light)"/>
      <path d="M75 105Q87 225 69 345M64 630Q55 760 68 900" fill="none" stroke="#47462f" stroke-width="2" stroke-linecap="round" opacity=".7"/>
    </svg>
    <section class="auth-form-panel<#if googleOnly> auth-google-panel</#if>" aria-label="Account sign-in">
      <div class="auth-card<#if googleOnly> auth-google-card</#if>">

        <p class="auth-eyebrow"><#if googleOnly>THE EDITORIAL ARCHIVE<#else>WELCOME TO MEDIAMESH</#if></p>
        <h2 id="kc-page-title"><#nested "header"></h2>
        <p class="auth-intro"><#if googleOnly>Sign in with your Google account to continue.<#else>Sign in to access your editorial workspace.</#if></p>
        <#if displayMessage && message?has_content && (message.type != 'warning' || !isAppInitiatedAction??)>
          <div class="auth-message ${message.type}" role="alert">${kcSanitize(message.summary)?no_esc}</div>
        </#if>
        <#if displayRequiredFields><p class="auth-required">* Required fields</p></#if>
        <#nested "form">
        <#nested "socialProviders">
        <#if displayInfo><div class="auth-info"><#nested "info"></div></#if>
      </div>
    </section>
  </main>
</body>
</html>
</#macro>
