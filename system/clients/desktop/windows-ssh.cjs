// Local Windows service only: fixed PowerShell, standard UAC, no remote shell API.
const fs = require('node:fs');
const path = require('node:path');
const {execFile} = require('node:child_process');
const STATUS = fs.readFileSync(path.join(__dirname, 'windows-ssh-status.ps1'), 'utf8');
const ENABLE = fs.readFileSync(path.join(__dirname, 'windows-ssh-enable.ps1'), 'utf8');
const encoded = source => Buffer.from(source, 'utf16le').toString('base64');
const ERRORS = {
  20: 'Windows could not initialize SSH setup.',
  21: 'OpenSSH installation did not complete. Check Windows Optional Features, Windows Update and organization policy.',
  22: 'Windows could not configure the local-subnet firewall rule.',
  23: 'Windows could not start sshd. Check its service and OpenSSH event log.',
  25: 'Another SSH setup is already running. Wait for it, then refresh status.',
  26: 'An existing custom sshd service was preserved. Manage that installation outside gBox.',
  27: 'Windows requires a restart to finish installing OpenSSH. Restart Windows when convenient, then enable SSH again.',
  28: 'A different firewall rule already uses the gBox rule name; it was preserved.',
  1223: 'Windows elevation was cancelled. SSH setup was not authorized.',
};
function elevationScript(executable) {
  const quote = value => "'" + value.replace(/'/g, "''") + "'";
  return `$ErrorActionPreference='Stop'\ntry {\n$p=Start-Process -FilePath ${quote(executable)} -ArgumentList '-NoProfile -NonInteractive -EncodedCommand ${encoded(ENABLE)}' -Verb RunAs -WindowStyle Hidden -PassThru\n$p.WaitForExit()\nexit $p.ExitCode\n} catch {\nif ($_.Exception.NativeErrorCode -eq 1223 -or $_.Exception.InnerException.NativeErrorCode -eq 1223) { exit 1223 }; exit 20\n}`;
}
function create({platform=process.platform, systemRoot=process.env.SystemRoot || 'C:\\Windows',
                 execute=execFile, getPreference=()=>false, savePreference=()=>{}, changed=()=>{}}={}) {
  const executable = path.win32.join(systemRoot, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
  let pending=null, querying=null, uncertain=false, startupDone=false;
  let last={supported:platform==='win32', state:platform==='win32'?'unknown':'unsupported', message:''};
  const snapshot=()=>({...last, auto_start:getPreference()===true, busy:!!pending||last.setup_result==='pending', uncertain});
  function run(source, timeout) {
    return new Promise(resolve=>{try {execute(executable, ['-NoProfile','-NonInteractive','-EncodedCommand',encoded(source)],
      {windowsHide:true,timeout,maxBuffer:32768,encoding:'utf8'}, (error,stdout)=>resolve({error,stdout}));}
      catch(error){resolve({error,stdout:''});}});
  }
  function status() {
    if(platform!=='win32')return Promise.resolve(snapshot());
    if(querying)return querying;
    querying=(async()=>{
      const result=await run(STATUS,15000);
      try {
        if(result.error)throw Error();
        const value=JSON.parse(result.stdout.trim().replace(/^\uFEFF/,''));
        if(!['installed','builtin','running','listening','reachable'].every(k=>typeof value[k]==='boolean'))throw Error();
        last={...last, ...value, supported:true, status_error:false, status_error_kind:null, message:last.status_error?'':last.message, state:!value.installed?'not_installed':!value.builtin?'custom_installation':
          !value.running?'stopped':value.reachable?'running':'unreachable', observed_at:Date.now()};
      } catch {
        const kind=result.error?.killed||result.error?.code==='ETIMEDOUT'?'status_timeout':
          result.error?.code==='ENOENT'?'powershell_missing':result.error?'status_command_failed':'status_response_invalid';
        const reason={status_timeout:'The Windows status command timed out.',powershell_missing:'Windows PowerShell could not be started.',
          status_command_failed:'The Windows status command failed.',status_response_invalid:'Windows returned an unreadable status response.'}[kind];
        last={...last,state:'unknown',status_error:true,status_error_kind:kind,message:reason+' You can explicitly try Force enable SSH (Administrator).'};
      }
      changed(snapshot());return snapshot();
    })().finally(()=>{querying=null;});
    return querying;
  }
  function enable() {
    if(platform!=='win32')return Promise.resolve(snapshot());
    if(pending)return pending;
    if(uncertain)return Promise.resolve(snapshot());
    pending=(async()=>{
      last={...last,setup_result:'pending',message:'Waiting for Windows elevation or SSH setup. Installation can take several minutes.'};
      changed(snapshot());
      const result=await run(elevationScript(executable),20*60*1000);
      const code=result.error?.code ?? 0;
      if(result.error?.killed || typeof code!=='number') {
        uncertain=true;
        last={...last,setup_result:'uncertain',message:'SSH setup outcome is unknown. Windows may still be working; refresh status. gBox will not repeat this request.'};
      } else last={...last,setup_result:code===0?'success':'failure',message:code===0?'Windows SSH setup completed.':ERRORS[code]||'Windows did not complete SSH setup.'};
      // An earlier Refresh may still report the pre-setup service state. Finish it,
      // then read again so setup never completes using that stale snapshot.
      if(querying)await querying;
      await status();
      return snapshot();
    })().finally(()=>{pending=null;changed(snapshot());});
    return pending.then(()=>snapshot());
  }
  async function preference(value) {
    if(typeof value!=='boolean')throw Error('Expected a boolean SSH startup preference.');
    await savePreference(value);changed(snapshot());return snapshot();
  }
  async function startup() {
    if(startupDone)return snapshot();
    startupDone=true;
    const current=await status();
    // No startup UAC unless this profile explicitly opted in. Never install/start
    // based on a failed status read or an existing custom service.
    if(getPreference()===true && ['not_installed','stopped'].includes(current.state))return enable();
    return current;
  }
  return {status,enable,preference,startup,snapshot};
}
module.exports={create,elevationScript,STATUS,ENABLE};
