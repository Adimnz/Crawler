/* Provider credentials and session tokens stay on the research server. */
(() => {
  'use strict';
  const page = document.getElementById('account-page');
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let state = null, csrf = '', factorId = '', challengeId = '', currentView = '', session = null;
  const params = new URLSearchParams(location.search);
  const date = value => value ? new Date(value).toLocaleString() : '';
  async function request(path, body) {
    const response = await fetch('/api/' + path, { method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin',
      headers: body === undefined ? {} : {'Content-Type':'application/json','X-Crawler-CSRF':csrf}, body: body === undefined ? undefined : JSON.stringify(body) });
    const result = await response.json().catch(() => ({error:'Start the Python research server to use accounts.'}));
    if (!response.ok) throw new Error(result.error || 'The account request did not complete.');
    if (result.csrf) csrf = result.csrf;
    return result;
  }
  async function refresh() { state = await request('accounts'); return state; }
  function destination() { const path = params.get('returnTo'); return path?.startsWith('/CRAWLER/') && !path.startsWith('//') ? path : '/CRAWLER/'; }
  function link(view) { return ({login:'login.html',register:'register.html',recover:'reset.html',verify:'verify.html',account:'account.html'})[view] || 'account.html'; }
  function open(view = 'account') { location.assign('/CRAWLER/' + link(view)); }
  function field(name, label, type='text', extra='') { return `<label>${label}<input name="${name}" type="${type}" ${extra}></label>`; }
  function form(action, content, title, submit) { return `<section class="account-card"><h2>${title}</h2><form data-account-action="${action}">${content}<button type="submit">${submit}</button><p class="account-feedback" role="status"></p></form></section>`; }
  function render(view) {
    if (!page) return;
    currentView = state?.needsMfa ? 'mfa' : view;
    const heading = {login:'Welcome back',register:'Create your research account',recover:'Reset your password',verify:'Verify your email',account:'Your account',mfa:'Verify your authenticator'}[currentView] || 'Your account';
    const email = field('email','Email','email','autocomplete="email" required');
    const password = field('password','Password','password','autocomplete="current-password" required maxlength="1024"');
    const newPassword = field('password','New password','password','autocomplete="new-password" minlength="12" maxlength="1024" required') + field('confirmPassword','Confirm password','password','autocomplete="new-password" minlength="12" required');
    let html = '';
    if (currentView === 'login') html = form('login', email + password + '<label><input type="checkbox" name="remember">Remember this device for 30 days</label>', 'Sign in', 'Sign in') + '<div class="account-actions"><a href="register.html">Create an account</a><a href="reset.html">Forgot password?</a><a href="verify.html">Verify email</a></div>';
    if (currentView === 'register') html = form('register', field('displayName','Display name','text','autocomplete="name" maxlength="150" required') + email + newPassword + '<label><input type="checkbox" name="acceptTerms" required>I accept responsibility for my account and understand that research claims require evidence review.</label>', 'Create account', 'Create account & verify email') + '<div class="account-actions"><a href="login.html">Already registered? Sign in</a><a href="verify.html">Enter an email verification code</a></div>';
    if (currentView === 'recover') html = state?.user ? form('password', newPassword + field('nonce','Email security code, if requested','text','autocomplete="one-time-code"'), 'Choose a new password', 'Save password') : form('recover', email, 'Request a recovery email', 'Send recovery email') + '<div class="account-actions"><a href="verify.html?type=recovery">Enter a recovery code</a><a href="login.html">Back to sign in</a></div>';
    if (currentView === 'verify') html = form('verify', email + field('code','Email verification code','text','autocomplete="one-time-code" required') + '<label>Verification purpose<select name="type"><option value="signup">New account</option><option value="recovery"' + (params.get('type') === 'recovery' ? ' selected' : '') + '>Password recovery</option></select></label>', 'Confirm your email', 'Verify') + form('resend', email, 'Need another email?', 'Resend verification');
    if (currentView === 'mfa') html = form('mfa-login', `<label>Authenticator<select name="factorId">${(state.factors || []).filter(f => f.status === 'verified').map(f => `<option value="${escape(f.id)}">${escape(f.friendly_name || 'Authenticator')}</option>`).join('')}</select></label>` + field('code','Six-digit authenticator code','text','inputmode="numeric" autocomplete="one-time-code" required pattern="[0-9]{6}"'), 'Complete sign in', 'Verify authenticator');
    if (currentView === 'account') {
      if (!state?.user) { render('login'); return; }
      html = `<p class="account-note">${escape(state.user.email)} · ${state.user.emailVerified ? 'Email verified' : 'Email verification pending'}</p><div class="account-actions"><a href="./">Open research ↗</a><button class="secondary" data-account-click="export">Export personal research</button><button class="secondary" data-account-click="logout">Sign out</button></div><div class="account-grid" style="margin-top:28px">` +
        form('profile', field('displayName','Display name','text',`value="${escape(state.user.displayName)}" maxlength="150" required`), 'Profile', 'Save profile') +
        form('password', field('currentPassword','Current password','password','autocomplete="current-password"') + newPassword + field('nonce','Email security code, if requested','text','autocomplete="one-time-code"') + '<div class="account-actions"><button type="button" class="secondary" data-account-click="reauthenticate">Send security code</button></div>', 'Change password', 'Change password') +
        `<section class="account-card"><h2>Authenticator security</h2><p class="account-note">Use a TOTP authenticator as a second sign-in factor.</p>${(state.factors || []).map(f => `<div class="account-session"><span>${escape(f.friendly_name || 'Authenticator')}<small>${escape(f.status)}</small></span><button class="secondary" data-account-click="mfa-remove" data-factor="${escape(f.id)}">Remove</button></div>`).join('')}<button class="secondary" data-account-click="mfa-enroll">Add authenticator</button><div id="mfa-enrollment"></div></section>` +
        `<section class="account-card"><h2>Active sessions</h2>${(state.sessions || []).map(s => `<div class="account-session"><span>${s.current ? 'This device' : 'Other session'}<small>Signed in ${date(s.createdAt)}<br>Expires ${date(s.expiresAt)}</small></span><button class="secondary" data-account-click="revoke-session" data-session="${escape(s.id)}">Revoke</button></div>`).join('')}<button class="secondary" data-account-click="logout-others">Sign out other devices</button></section><section class="account-card wide" id="account-research-list"><h2>My Research</h2><p class="account-note">Loading saved boards…</p></section>` +
        form('delete', '<p class="account-note">This deletes your account and its private boards, annotations, tasks and portfolios. Shared source evidence is retained.</p>' + field('confirmation','Type your account email to confirm','email','autocomplete="off" required'), 'Delete account', 'Delete account & private research') + '</div><p id="account-global-feedback" class="account-feedback" role="status"></p>';
    }
    if (!state?.configured) html = `<p class="account-feedback">Connect the Supabase project to enable personal accounts. Local research boards remain available in the app.</p>` + html;
    const setup = `<details class="account-setup" ${!state?.configured ? 'open' : ''}><summary>Account provider setup</summary>${form('setup', field('projectURL','Supabase project URL','url',`value="${escape(state?.projectURL || 'https://lowvafwxnuqtogsfkmkd.supabase.co')}" required`) + field('publishableKey','Publishable / anon key','password','autocomplete="off" required') + '<p class="account-note">Find the publishable key in your Supabase project settings. Keep secret service keys on the server. Account configuration requires the research server owner.</p>', 'Connect Supabase Auth', 'Verify & connect')}</details>`;
    page.innerHTML = `<h1>${heading}</h1>${currentView === 'account' ? '' : '<p>Save private research boards and continue investigating across devices.</p>'}${html}${setup}`;
    const setupPanel=page.querySelector('.account-setup');
    if(!session?.ownerAuthorized)setupPanel?.remove();
    else setupPanel.insertAdjacentHTML('beforeend',`<p class="account-note">In Supabase Authentication, enable email confirmation and allow this redirect URL:</p><code class="account-callback">${escape(location.origin+'/CRAWLER/account.html?view=callback')}</code><p class="account-note">Configure email delivery in the project. Account deletion also needs the supplied SQL function or a server-only service key; see CRAWLER/README.md.</p>`);
    if (currentView === 'account') loadResearch();
  }
  async function loadResearch() {
    try {
      const data = await request('my-research');
      const target = document.getElementById('account-research-list'); if (!target) return;
      target.innerHTML = '<h2>My Research</h2>' + (data.boards || []).map(b => `<a class="account-board" href="./?board=${encodeURIComponent(b.id)}"><span>${escape(b.title)}<small>${escape(b.folder || 'Unfiled')} · ${date(b.updatedAt)}</small></span><span>Open board ↗</span></a>`).join('') + (!data.boards?.length ? '<p class="account-note">Start a topic and save its observation board to see it here.</p>' : '');
    } catch (error) { const target = document.getElementById('account-research-list'); if (target) target.textContent = error.message; }
  }
  function download(value) { const url = URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'})); const a = document.createElement('a'); a.href=url; a.download='my-research.json'; a.click(); setTimeout(()=>URL.revokeObjectURL(url),1000); }
  async function mfaVerify(id, code) {
    const challenge = await request('accounts/mfa-challenge', {factorId:id});
    return request('accounts/mfa-verify', {factorId:id,challengeId:challenge.challengeId,code});
  }
  document.addEventListener('submit', async event => {
    const form = event.target.closest('[data-account-action]'); if (!form) return;
    event.preventDefault(); const action=form.dataset.accountAction, button=form.querySelector('button[type=submit]'), feedback=form.querySelector('[role=status]');
    const values = Object.fromEntries(new FormData(form));
    for (const checkbox of form.querySelectorAll('input[type=checkbox]')) values[checkbox.name]=checkbox.checked;
    button.disabled=true; feedback.textContent='Working…';
    try {
      let result;
      if (action === 'mfa-login' || action === 'mfa-finish') result=await mfaVerify(values.factorId || factorId,values.code);
      else result=await request('accounts/'+action,values);
      for (const input of form.querySelectorAll('input[type=password]')) input.value='';
      if (action==='login' || action==='mfa-login') { state=result; if(state.needsMfa)render('mfa');else location.assign(destination()); }
      else if (action==='verify') { state=result;render(result.recovery?'recover':'account'); }
      else if (action==='delete') location.assign('/CRAWLER/');
      else if (action==='mfa-finish' || action==='profile' || action==='setup') { await refresh();render(action==='setup'?'login':'account'); }
      else feedback.textContent=result.message || (action==='password'?'Password updated.':'Saved.');
    } catch(error){feedback.textContent=error.message;} finally{values.password='';values.currentPassword='';values.confirmPassword='';values.publishableKey='';button.disabled=false;}
  });
  document.addEventListener('click', async event => {
    const button=event.target.closest('[data-account-click]');if(!button)return;
    const action=button.dataset.accountClick, feedback=document.getElementById('account-global-feedback');button.disabled=true;
    try{
      if(action==='export'){download(await request('my-research/export'));return;}
      if(action==='mfa-enroll'){
        const result=await request('accounts/mfa-enroll',{});factorId=result.factorId;
        document.getElementById('mfa-enrollment').innerHTML=`<p class="account-note">Add this setup key to your authenticator, then enter its code:</p><p class="account-secret">${escape(result.secret)}</p>`+form('mfa-finish',field('code','Authenticator code','text','inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" required'),'Verify authenticator','Enable MFA');return;
      }
      const result=await request('accounts/'+(action==='logout-others'?'logout':action),action==='revoke-session'?{sessionId:button.dataset.session}:action==='mfa-remove'?{factorId:button.dataset.factor}:action==='logout-others'?{others:true}:{});
      if(result.signedOut){location.assign('/CRAWLER/login.html');return;}
      if(action==='reauthenticate'){if(feedback)feedback.textContent=result.message;return;}
      await refresh();render('account');
    }catch(error){if(feedback)feedback.textContent=error.message;}finally{button.disabled=false;}
  });
  async function initialize() {
    if (!page) {
      try {
        state=await request('accounts');
        const top=document.querySelector('.start-topbar');if(top&&!document.getElementById('research-account-link')){
          const a=document.createElement('a');a.id='research-account-link';a.className='start-account-link';a.href='/CRAWLER/account.html';a.textContent=state.user?.displayName||'Account';top.append(a);
        }
      }catch{ /* Static mode retains existing research features. */ }
      return;
    }
    const fragment=new URLSearchParams(location.hash.slice(1)), tokenHash=params.get('token_hash');
    if(fragment.has('access_token')||tokenHash)history.replaceState(null,'',location.pathname);
    try {
      session=await request('session');csrf=session.csrf;await refresh();
      if(fragment.has('access_token') || tokenHash){
        const result=tokenHash?await request('accounts/verify',{tokenHash,type:params.get('type')||'signup'}):await request('accounts/callback',{accessToken:fragment.get('access_token'),refreshToken:fragment.get('refresh_token')});
        state=result;render(params.get('type')==='recovery'||fragment.get('type')==='recovery'?'recover':'account');return;
      }
      render(params.get('view')==='callback'?'account':document.body.dataset.accountView || 'account');
    }catch(error){page.innerHTML=`<h1>Account connection unavailable</h1><p class="account-feedback">${escape(error.message)}</p><a href="./">Return to the research app ↗</a>`;}
  }
  window.CrawlerAccounts={open,get state(){return state;}};
  initialize();
})();
