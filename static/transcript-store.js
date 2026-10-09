export class TranscriptStore {
  constructor() { this.items = new Map(); this.arrival = 0; }
  apply(event) {
    if (!event.item_id) return null;
    let item = this.items.get(event.item_id);
    if (!item) {
      item = {id:event.item_id, sequence: Number.MAX_SAFE_INTEGER, arrival:this.arrival++,
        source:'', translation:'', rawSource:'', rawTranslation:'', revisions:[], version:0, final:false, translationFinal:false, error:'', at:new Date()};
      this.items.set(item.id, item);
    }
    if (event.sequence !== undefined) item.sequence = event.sequence;
    if (event.type === 'source.delta' && !item.final) item.source += event.delta || '';
    if (event.type === 'source.final') { item.rawSource=event.text;item.initialSource=event.initial_text??event.text; if(!item.revisions.some(r=>!r.undone))item.source=event.text; item.version++; item.final=true;item.languages=event.languages;item.start=event.start;item.end=event.end;item.recovered=event.recovered; }
    if (event.type === 'source.final' && !event.text && !item.translationFinal && !item.revisions.some(r=>!r.undone)) item.translation='';
    if (event.type === 'translation.preview' && !item.final && !item.translationFinal && !item.revisions.some(r=>!r.undone) && event.revision>(item.previewRevision||0)) {item.translation=event.text;item.previewRevision=event.revision;item.version++;}
    if (event.type === 'translation.final') { item.rawTranslation=event.text;if(!item.revisions.some(r=>!r.undone))item.translation=event.text;item.version++;item.error='';item.translationFinal=true; }
    if (event.type === 'segment.error') item.error = `${event.module}: ${event.message}`;
    return item;
  }
  revise(change) {
    const item=this.items.get(change.item_id);
    if(!item || item.version!==change.version)return false;
    if(change.kind!=='user_confirmed' && change.source!==item.source)return false;
    item.revisions.push({beforeSource:item.source,beforeTranslation:item.translation,...change,at:new Date().toISOString()});
    item.source=change.source;item.translation=change.translation;item.version++;return true;
  }
  undo(id) {
    const item=this.items.get(id);if(!item?.revisions.length)return;
    const last=[...item.revisions].reverse().find(r=>!r.undone);
    if(!last)return;last.undone=true;
    const active=item.revisions.filter(r=>!r.undone).at(-1);
    item.source=active?.source??item.rawSource;item.translation=active?.translation??item.rawTranslation;item.version++;
  }
  ordered() { return [...this.items.values()].sort((a,b) => a.sequence-b.sequence || a.arrival-b.arrival); }
  latest() { return this.ordered().filter(i=>i.source || i.translation).at(-1); }
}
