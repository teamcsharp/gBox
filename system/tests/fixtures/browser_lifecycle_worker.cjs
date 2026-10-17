const {withPage}=require('../../scripts/browser_lifecycle.cjs');
withPage(async(evaluate,send,info)=>{if(process.argv.includes('--exit'))process.stdout.write(JSON.stringify(info)+'\n',()=>process.exit(0));else console.log(JSON.stringify(info));await new Promise(()=>{});}).catch(e=>{console.error(e.message);process.exitCode=1;});
