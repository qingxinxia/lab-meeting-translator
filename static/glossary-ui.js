const $=id=>document.getElementById(id);
let terms=[];
const message=text=>{$('glossaryMessage').textContent=text;};
const topic=()=>$('glossaryTopic').value;
async function request(path,options) {
  const response=await fetch(path,options);const body=await response.json();
  if(!response.ok)throw Error(typeof body.detail==='string'?body.detail:'词表数据无效');return body;
}
function edit(term={}) {
  $('termEn').value=term.term||'';$('termJa').value=term.ja||'';$('termZh').value=term.zh||'';
  $('termAliases').value=(term.aliases||[]).join(', ');$('termNotes').value=term.notes||'';$('termStatus').value=term.status||'confirmed';
}
function render() {
  const query=$('termSearch').value.toLowerCase();$('termsList').replaceChildren();
  for(const term of [...terms].sort((a,b)=>(b.status==='candidate')-(a.status==='candidate'))) {
    if(!JSON.stringify(term).toLowerCase().includes(query))continue;
    const button=document.createElement('button');button.className='term-row';
    const title=document.createElement('strong');title.textContent=term.term;
    const detail=document.createElement('span');detail.textContent=`${term.ja||'—'} → ${term.zh||'待补充中文'} · ${{confirmed:'已确认',candidate:'候选词',archived:'已归档'}[term.status]} · 出现 ${term.uses} 段`;
    if(term.status==='candidate')detail.className='candidate';button.append(title,detail);button.onclick=()=>edit(term);$('termsList').append(button);
  }
}
async function load() {
  const body=await request(`/api/topics/${topic()}/terms`);terms=body.terms;
  $('glossaryStorage').textContent=`本地 SQLite：${body.database} · 已确认 ${body.counts.confirmed} · 候选 ${body.counts.candidate} · 归档 ${body.counts.archived}。候选不参与识别/翻译提示。`;
  render();
}
async function open() {$('glossaryTopic').value=$('topicSelect').value;$('glossaryDialog').showModal();edit();message('');try{await load();}catch(error){message(error.message);}}
async function save(term) {return request(`/api/topics/${topic()}/terms`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(term)});}
$('glossaryBtn').onclick=open;$('manageTermsBtn').onclick=open;
$('closeGlossary').onclick=()=>$('glossaryDialog').close();
$('glossaryTopic').onchange=async()=>{edit();message('');try{await load();}catch(error){message(error.message);}};
$('termSearch').oninput=render;$('newTerm').onclick=()=>edit();
$('termForm').onsubmit=async event=>{
  event.preventDefault();
  try {
    await save({term:$('termEn').value,ja:$('termJa').value,zh:$('termZh').value,
      aliases:$('termAliases').value.split(/[,，]/).map(v=>v.trim()).filter(Boolean),notes:$('termNotes').value,status:$('termStatus').value});
    await load();message('已持久保存，修订记录保留。之后的翻译使用最新已确认术语。');
  }catch(error){message(error.message);}
};
$('exportTerms').onclick=()=>{
  const url=URL.createObjectURL(new Blob([JSON.stringify({topic:topic(),terms},null,2)],{type:'application/json'}));
  const link=document.createElement('a');link.href=url;link.download=`glossary-${topic()}.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};
$('importTerms').onclick=()=>$('termsFile').click();
$('termsFile').onchange=async()=>{
  const file=$('termsFile').files[0];let saved=0;
  try {
    if(!file)return;if(file.size>1024*1024)throw Error('文件超过 1 MB');
    const body=JSON.parse(await file.text());
    if(body.topic && body.topic!==topic())throw Error('文件专题与当前词库不同，请先切换词库');
    const rows=Array.isArray(body)?body:body.terms;if(!Array.isArray(rows)||rows.length>500)throw Error('需要 terms 数组，最多 500 项');
    if(!window.confirm(`将导入 ${rows.length} 条术语到当前词库。同名术语会覆盖，旧值保留在修订历史中。继续？`))return;
    for(const row of rows){await save({term:row.term,ja:row.ja||'',zh:row.zh||'',aliases:row.aliases||[],notes:row.notes||'',status:row.status||'candidate'});saved++;}
    await load();message(`已导入 ${saved} 条术语。`);
  }catch(error){message(`导入停止（已保存 ${saved} 条）：${error.message}`);await load().catch(()=>{});}
  finally{$('termsFile').value='';}
};
