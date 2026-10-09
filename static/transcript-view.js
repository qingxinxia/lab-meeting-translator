export const nearTranscriptBottom=list=>list.scrollHeight-list.scrollTop-list.clientHeight<80;
// Keep existing nodes in place: re-appending every row disrupts readers scrolling back.
export function orderTranscriptRows(list,rows){
  rows.forEach((row,index)=>{if(list.children[index]!==row)list.insertBefore(row,list.children[index]||null);});
}
