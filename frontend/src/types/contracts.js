/** @typedef {{id:number, title:string, payload:object, author:string}} BusinessCase */
/** @typedef {{id:number, case_id:number, case_title:string, status:'queued'|'running'|'complete'|'failed', version:number, attempts:number, payload_digest:string, evidence_id:number|null, reviewed_at:string|null}} Run */
/** @typedef {{id:number, run_id:number, digest:string, payload_digest:string, version:number, attempt:number, run_version:number, run_attempts:number, reviewed_at:string|null, reviewer:string|null, report:{summary:string, metrics:object, sections:Array}}} Evidence */
