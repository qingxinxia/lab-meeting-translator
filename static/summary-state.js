// Assign each utterance by its end time so boundary-crossing turns appear exactly once.
export function summaryWindows(items, elapsed, minutes=5, ended=false) {
  const size=minutes*60, cutoff=ended?elapsed:Math.floor(elapsed/60)*60, groups=new Map();
  for(const item of items){
    if(!item.final||!Number.isFinite(item.end)||item.end>cutoff||!item.source)continue;
    const start=Math.floor(Math.max(0,item.end-0.001)/size)*size;
    if(!groups.has(start))groups.set(start,[]);groups.get(start).push(item);
  }
  return [...groups].sort((a,b)=>a[0]-b[0]).map(([start,segments])=>({
    key:String(start),start,end:Math.min(start+size,cutoff),final:ended||cutoff>=start+size,segments,
    signature:JSON.stringify(segments.map(i=>[i.id,i.version]))
  }));
}
export const snapshotSegments=items=>items.map(i=>({item_id:i.id,source:i.source,translation:i.translationFinal===false&&!i.revisions?.some(r=>!r.undone)?'':i.translation,version:i.version}));
export const timeLabel=n=>`${Math.floor(n/60).toString().padStart(2,'0')}:${Math.floor(n%60).toString().padStart(2,'0')}`;
