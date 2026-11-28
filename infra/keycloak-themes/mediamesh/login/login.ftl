<#import "template.ftl" as layout>
<@layout.registrationLayout displayInfo=false googleOnly=true; section>
  <#if section == "header">
    Welcome to<br />MediaMesh
  <#elseif section == "form">
    <#assign googleAvailable = false>
    <#if social?? && social.providers??>
      <#list social.providers as provider>
        <#if provider.alias == "google">
          <#assign googleAvailable = true>
          <div class="auth-provider-area">
            <a id="social-google" class="google-signin" href="${provider.loginUrl}">
              <img src="/google-signin-light.png" alt="Sign in with Google" width="216" height="48" />
            </a>

          </div>
        </#if>
      </#list>
    </#if>
    <#if !googleAvailable>
      <div class="auth-message" role="alert">Google sign-in is unavailable. Please contact your administrator.</div>
    </#if>

  </#if>
</@layout.registrationLayout>
