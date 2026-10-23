'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const esc = s => String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmt = n => Number(n).toLocaleString('en-US');
  let latest = null, requestId = 0;
  const questions = {
    clean: 'Are the datasets clean and correct?',
    gaps: 'What is missing for this county and storm?',
    defend: 'What conclusions can I defend?',
    collect: 'What data should I collect next?',
    centerpoint: 'Why is CenterPoint shown separately?'
  };
  Object.entries(questions).forEach(([id,title])=>$('evidence-question').add(new Option(title,id)));
  function answer() {
    if (!latest) return;
    const d=latest,s=d.selection;
    let title=questions[$('evidence-question').value],text='';
    switch($('evidence-question').value) {
      case 'clean':
        text=d.integrity.passed
          ? `Yes. Every file passes the processing and integrity checks: payment totals reconcile to the source claims, and keys, time alignment and fingerprints all verify. Gaps are marked as unknown rather than filled in, so every number shown traces to a source record.`
          : `The live file checks failed: ${d.integrity.detail} The stored summaries are not currently verified. Resolve the issue and run the checks again.`;
        break;
      case 'gaps':
        text=`${s.county_name} has ${fmt(s.usable_outage_quarters)} usable outage snapshots (${s.usable_outage_percent}% of the window), ${s.weather_hours} hours of weather, and ${fmt(s.claim_count)} assigned NFIP claims. Any hours without a record are shown as gaps in the charts, so you can see exactly what each comparison rests on.`;
        break;
      case 'defend':
        text=d.integrity.passed
          ? `You can compare weather, county outage counts and insured flood payments across ${d.overview.independent_storms} storms, and back each finding with official reports and page-cited quotes. ${d.verdict}`
          : 'Do not rely on the displayed comparisons until the live file-validation issue is resolved. The source and scope limitations also remain after file checks pass.';
        break;
      case 'collect':
        text=`For ${$('analysis-goal').selectedOptions[0].text.toLowerCase()}, start with ${d.next_data[0].name.toLowerCase()}. ${d.next_data[0].benefit} See the collection checklist below for the fields needed and the reason for each request.`;
        break;
      case 'centerpoint':
        text='EAGLE-I county totals can include multiple utilities. CenterPoint’s eight published Beryl milestones cover its Houston Electric service territory, which is a different geographic area. Allocating those milestones to counties would invent data. The app preserves publication times, reported rounding, and phrases such as “more than” and “nearly”; the milestones are not reconciled meter-level measurements.';
    }
    $('evidence-answer').innerHTML=`<h3>${esc(title)}</h3><p>${esc(text)}</p><div class="evidence-links">${d.evidence_links.map(l=>`<a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.label)}</a>`).join('')}</div>`;
  }
  function show(d) {
    latest=d;
    $('live-status').className='status-pill '+(d.integrity.passed?'checked':'failed');
    $('live-status').textContent=d.integrity.passed?'File checks passed':'File checks failed';
    $('readiness-verdict').textContent=d.verdict;
    $('last-checked').textContent='Checked '+new Date(d.integrity.checked_at_utc).toLocaleString()+'. '+d.integrity.meaning;
    const s=d.selection;
    $('selection-coverage').innerHTML=`<strong>${s.usable_outage_percent}%</strong><span>usable outage snapshots</span><p>${esc(s.county_name)} · ${esc($('storm').selectedOptions[0].text)}<br>${fmt(s.usable_outage_quarters)} of ${fmt(s.expected_outage_quarters)} quarter-hours recorded</p>`;
    $('goal-meaning').textContent=$('analysis-goal').value==='history'?'Historical comparisons are ready to use.':$('analysis-goal').value==='forecasting'?'The checklist below shows what turns this into a tested forecast.':'The checklist below shows what turns this into resource priorities.';
    $('next-data').innerHTML=d.next_data.map(n=>`<article class="need-card"><small>${esc(n.priority)}</small><h3>${esc(n.name)}</h3><p>${esc(n.benefit)}</p><details><summary>Fields to request</summary><p>${esc(n.fields)}</p></details></article>`).join('');
    $('live-checks').innerHTML=d.checks.map(c=>`<li>${esc(c)}</li>`).join('');
    $('readiness-error').hidden=true;
    // Historical build evidence remains available below, while this banner reflects current files.
    $('validation').textContent=`Stored build report: ${fmt(d.overview.hourly_rows)} hourly rows, ${d.overview.county_storm_rows} county–storm summaries, ${fmt(d.overview.assigned_claims)} assigned claims. Current file validation: ${d.integrity.passed?'passed with source limitations':'FAILED; inspect the readiness panel before using results'}.`;
    answer();
  }
  async function refresh(force=false) {
    const id=++requestId;
    $('recheck').disabled=true;
    $('live-status').textContent='Checking local files…';
    $('live-status').className='status-pill pending';
    $('evidence-answer').setAttribute('aria-busy','true');
    const query=new URLSearchParams({storm:$('storm').value,county:$('county').value,goal:$('analysis-goal').value,refresh:force?'1':'0'});
    try {
      const response=await fetch('/api/readiness?'+query);
      if (!response.ok) throw new Error('Readiness service unavailable.');
      const data=await response.json();
      if(id===requestId)show(data);
    } catch(error) {
      if(id!==requestId)return;
      latest=null;
      $('live-status').textContent='Live checks unavailable';
      $('live-status').className='status-pill failed';
      $('readiness-error').hidden=false;
      $('readiness-error').textContent='Start the local application with python app.py and open its printed address. The static explorer can still show the last build, but current file checks are unavailable.';
      $('readiness-verdict').textContent='Current data integrity has not been checked.';
      $('evidence-answer').textContent='Evidence answers require a successful response from the local application.';
      $('next-data').replaceChildren();$('selection-coverage').replaceChildren();$('live-checks').replaceChildren();
    } finally {
      if(id===requestId){$('recheck').disabled=false;$('evidence-answer').setAttribute('aria-busy','false');}
    }
  }
  $('evidence-question').addEventListener('change',answer);
  $('recheck').addEventListener('click',()=>refresh(true));
  ['storm','county','analysis-goal'].forEach(id=>$(id).addEventListener('change',()=>refresh()));
  // Map and table selections update the same county control without firing change events.
  $('map').addEventListener('click',e=>{if(e.target.closest('path'))refresh();});
  $('map').addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' ')refresh();});
  $('summary').addEventListener('click',e=>{if(e.target.closest('button'))refresh();});
  // Harvey summary buttons set both county and storm (to Harvey) before this bubbling listener runs.
  $('harveySummary').addEventListener('click',e=>{if(e.target.closest('button'))refresh();});
  if(window.STORM_DATA)refresh();
})();
