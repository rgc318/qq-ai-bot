// Exercise the actual installed app's form binding/save path with HTML-derived IDs.
// No browser, API requests, production configuration, or model calls are used.
const fs=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const [scriptPath,htmlPath]=process.argv.slice(2);
const source=fs.readFileSync(scriptPath,'utf8').replace(/\binit\(\);\s*$/,'');
const html=fs.readFileSync(htmlPath,'utf8');
const ids=[...html.matchAll(/\bid=["']([^"']+)/g)].map(m=>m[1]);

function formRun({originalValue,controlPresent=false,changeValue}) {
    const elements=new Map(ids.map(id=>[id,{value:'',checked:false}]));
    if(controlPresent)elements.set('opt_astrbot',{value:'',checked:false});
    const sandbox={console,URL,setTimeout:()=>0,document:{getElementById:id=>elements.get(id)||null,addEventListener:()=>{}},window:{addEventListener:()=>{}}};
    vm.createContext(sandbox);vm.runInContext(source,sandbox);
    vm.runInContext(`
      state.permission_config=normalizePermissionConfig(mockConfig.permission_config);
      state.usage_config=normalizeUsageConfig(mockConfig.usage_config);
      state.cache_config=normalizeCacheConfig(mockConfig.cache_config);
      state.reply_config=normalizeReplyConfig(mockConfig.reply_config);
      state.persona_config=normalizePersonaProfiles(mockConfig.persona_config);
      state.router_config={...mockConfig.router_config};
      state.optimizer_config={...mockConfig.optimizer_config,use_astrbot_provider:${originalValue}};
      bindBasicFields();
    `,sandbox);
    if(controlPresent && changeValue!==undefined)elements.get('opt_astrbot').checked=changeValue;
    return vm.runInContext('buildPayload().optimizer_config.use_astrbot_provider',sandbox);
}

assert.equal(formRun({originalValue:false}),false);
assert.equal(formRun({originalValue:true}),true);
assert.equal(formRun({originalValue:true,controlPresent:true,changeValue:false}),false);
assert.equal(formRun({originalValue:false,controlPresent:true,changeValue:true}),true);
console.log('PASS: actual form binding and payload generation; absent-control true/false preservation and present-control editing (4 cases)');
