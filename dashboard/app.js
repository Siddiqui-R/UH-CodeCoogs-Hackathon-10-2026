'use strict';
(() => {
  const d = window.STORM_DATA;
  if (!d) { const el=document.getElementById('fatal');el.hidden=false;el.textContent='Dataset missing. Run python -m stormdata.build, then reload.'; return; }
  const $=id=>document.getElementById(id), ns='http://www.w3.org/2000/svg';
  const storm=$('storm'),county=$('county'),metric=$('metric');
  const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmt=(v,dp=0)=>v===null||v===undefined?'Unknown':Number(v).toLocaleString('en-US',{maximumFractionDigits:dp});
  const money=v=>v===null?'Unknown':new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:0}).format(v);
  const create=(tag,attrs={},text)=>{const el=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([k,v])=>el.setAttribute(k,v));if(text!==undefined)el.textContent=text;return el;};
  Object.entries(d.storms).forEach(([key,s])=>storm.add(new Option(`${s.name} (${s.year})`,key)));
  const counties=Object.fromEntries(d.summary.map(r=>[r.county_fips,r.county_name]));
  Object.entries(counties).sort((a,b)=>a[1].localeCompare(b[1])).forEach(([key,name])=>county.add(new Option(name,key)));
  storm.value='Hurricane_Beryl_2024';county.value='48201';
  let countyMap=null,countyLayer=null;
  function drawMap(rows) {
    $('mapTitle').textContent=metric.selectedOptions[0].text;
    if(!window.L){$('map').textContent='The map library did not load. Reload the page to try again.';return;}
    // Build the map only once its page is visible; a hidden container has no size.
    if(!countyMap&&$('map').offsetWidth===0)return;
    if(!countyMap){
      countyMap=baseMap('map',false);countyLayer=L.layerGroup().addTo(countyMap);
      const fitCounties=()=>countyMap.fitBounds(L.geoJSON(d.counties).getBounds().pad(0.02));
      fitCounties();
      window.refitCounty=()=>{countyMap.invalidateSize();fitCounties();};
    }
    countyLayer.clearLayers();
    const vals=rows.map(r=>r[metric.value]).filter(v=>v!==null),min=Math.min(...vals),max=Math.max(...vals);
    const dp=metric.value==='total_precipitation_in'?1:0;
    const shade=v=>{const t=v===null||v===undefined?null:max===min?.5:(v-min)/(max-min);if(t===null)return '#cfd6d8';const a=[226,236,238],b=[31,111,120];return `rgb(${a.map((n,i)=>Math.round(n+(b[i]-n)*t)).join(',')})`;};
    for(const f of d.counties.features){
      const id=f.properties.id,r=rows.find(r=>r.county_fips===id);
      if(!r)continue;
      const v=r[metric.value],selected=id===county.value;
      const value=metric.value==='nfip_total_net_payment_usd'?money(v):fmt(v,dp);
      L.geoJSON(f,{style:{fillColor:shade(v),fillOpacity:.72,color:selected?'#22313a':'#ffffff',weight:selected?4:2,opacity:1}})
        .bindTooltip(`<strong>${esc(r.county_name)}</strong><br>${esc(metric.selectedOptions[0].text)}: ${esc(value)}`,{sticky:true})
        .on('click',()=>{county.value=id;render();})
        .addTo(countyLayer);
      const sample=d.hourly.find(h=>h.county_fips===id);
      L.marker([sample.weather_point_latitude,sample.weather_point_longitude],{interactive:false,keyboard:false,
        icon:L.divIcon({className:'county-label'+(selected?' selected':''),html:`<div class="cl"><b>${esc(r.county_name)}</b><span>${esc(value)}</span></div>`,iconSize:null})}).addTo(countyLayer);
    }
  }
  function chart(parent,rows,column,label,color,bars=false){
    const heading=document.createElement('h3');heading.textContent=label;parent.append(heading);
    const svg=create('svg',{viewBox:'0 0 560 130',role:'img','aria-label':label});svg.append(create('title',{},label));parent.append(svg);
    const vals=rows.map(r=>r[column]).filter(v=>v!==null),max=Math.max(1,...vals),left=48,right=550,top=10,bottom=105;
    const x=i=>left+i*(right-left)/Math.max(1,rows.length-1),y=v=>bottom-v/max*(bottom-top);
    [0,.5,1].forEach(t=>{const yy=y(max*t);svg.append(create('line',{x1:left,x2:right,y1:yy,y2:yy,stroke:'#e1e7df'}));svg.append(create('text',{x:left-7,y:yy+3,'text-anchor':'end',class:'axis'},fmt(max*t,max<5?2:0)));});
    let path='';
    rows.forEach((r,i)=>{
      const v=r[column];if(v===null){path+=' ';return;}
      const tip=`${r.time_local} · ${fmt(v,2)}${column.startsWith('outage')?` · ${r.outage_observed_quarters}/4 quarter-hours`:''}`;
      if(bars){const bar=create('rect',{x:x(i)-1,y:y(v),width:Math.max(1,(right-left)/rows.length),height:bottom-y(v),fill:color});bar.append(create('title',{},tip));svg.append(bar);}
      else{
        path+=(i===0||rows[i-1][column]===null?'M':'L')+x(i)+','+y(v);
        const dot=create('circle',{cx:x(i),cy:y(v),r:2.5,fill:color,opacity:column.startsWith('outage')&&r.outage_observed_quarters<4?.45:1});dot.append(create('title',{},tip));svg.append(dot);
      }
    });
    if(!bars)svg.insertBefore(create('path',{d:path,stroke:color,'stroke-width':1.5,fill:'none'}),svg.children[4]||null);
    [0,Math.floor(rows.length/2),rows.length-1].forEach(i=>svg.append(create('text',{x:x(i),y:124,'text-anchor':i===0?'start':i===rows.length-1?'end':'middle',class:'axis'},rows[i].time_local.slice(5,16).replace('T',' '))));
    if(!vals.length)svg.append(create('text',{x:280,y:60,'text-anchor':'middle',class:'axis'},'No source records — unknown'));
  }
  function renderHarvey(){
    const h=d.harvey,isHarvey=storm.value==='Hurricane_Harvey_2017';
    $('harveyIntro').textContent=isHarvey?'These two Harvey-only sources sit beside the four-storm data. They are not merged into it.':`These sources cover Harvey only, so they do not change the ${d.storms[storm.value].name} figures above. Select Harvey to compare them with that storm's records.`;
    const eaglei=Object.fromEntries(d.summary.filter(r=>r.storm_event==='Hurricane_Harvey_2017').map(r=>[r.county_fips,r]));
    $('harveySummary').innerHTML=h.summary.map(r=>{const e=eaglei[r.county_fips],presence=e.outage_record_presence_fraction;return `<tr class="${r.county_fips===county.value?'active':''}"><td><button data-fips="${r.county_fips}">${esc(r.county_name)}</button></td><td>${fmt(r.zips_assigned)}</td><td>${fmt(r.zip_outage_peak_daily_count)}</td><td>${esc(r.zip_outage_peak_date||'Unknown')}</td><td>${fmt(r.zip_outage_peak_pct_of_reporting_customers,1)}%</td><td>${presence?fmt(e.outage_peak_customers_observed):'No records'}</td><td>${fmt(r.fema_total_observations)}</td><td>${fmt(r.fema_major_destroyed_total)}</td></tr>`;}).join('');
    $('harveySummary').querySelectorAll('button').forEach(b=>b.onclick=()=>{county.value=b.dataset.fips;storm.value='Hurricane_Harvey_2017';render();});
    const days=h.county_daily.filter(r=>r.county_fips===county.value),name=counties[county.value];
    const box=$('harveyChart');box.replaceChildren();
    const heading=document.createElement('h3');heading.textContent=`${name}: customers out in each daily snapshot (ZIP file)`;box.append(heading);
    const svg=create('svg',{viewBox:'0 0 560 130',role:'img','aria-label':heading.textContent});svg.append(create('title',{},heading.textContent));box.append(svg);
    const vals=days.map(r=>r.outage_count_sum).filter(v=>v!==null),max=Math.max(1,...vals),left=56,right=550,top=10,bottom=105,step=(right-left)/Math.max(1,days.length);
    const y=v=>bottom-v/max*(bottom-top);
    [0,.5,1].forEach(t=>{const yy=y(max*t);svg.append(create('line',{x1:left,x2:right,y1:yy,y2:yy,stroke:'#e1e7df'}));svg.append(create('text',{x:left-7,y:yy+3,'text-anchor':'end',class:'axis'},fmt(max*t)));});
    days.forEach((r,i)=>{
      const x=left+i*step;
      if(r.outage_count_sum!==null){const bar=create('rect',{x:x+step*.15,y:y(r.outage_count_sum),width:step*.7,height:bottom-y(r.outage_count_sum),fill:'#1f6f78'});bar.append(create('title',{},`${r.report_date} · ${fmt(r.outage_count_sum)} customers out · ${fmt(r.outage_pct_of_reporting_zip_customers,1)}% of ${fmt(r.reporting_zip_customers_sum)} in ${r.zips_reporting} reporting ZIPs`));svg.append(bar);}
      svg.append(create('text',{x:x+step/2,y:124,'text-anchor':'middle',class:'axis'},r.report_date.slice(5)));
    });
    if(!vals.length)svg.append(create('text',{x:280,y:60,'text-anchor':'middle',class:'axis'},'No ZIP records — unknown'));
  }
  function render(){
    const rows=d.summary.filter(r=>r.storm_event===storm.value),r=rows.find(r=>r.county_fips===county.value);
    const hours=d.hourly.filter(r=>r.storm_event===storm.value&&r.county_fips===county.value);
    $('scope').textContent=`${r.county_name} County, ${d.storms[storm.value].name}. Weather and outage window ${hours[0].time_local.slice(0,10)} through ${hours.at(-1).time_local.slice(0,10)} (America/Chicago). Claim window ${r.nfip_claim_window_start} through ${r.nfip_claim_window_end}.`;
    $('cards').innerHTML=[['Rainfall',fmt(r.total_precipitation_in,2)+' in','Sum over supplied weather window'],['Peak wind gust',fmt(r.peak_wind_gust_mph,1)+' mph','Reanalysis at county reference point'],['Peak observed out',fmt(r.outage_peak_customers_observed),`${fmt(100*r.outage_record_presence_fraction,1)}% source-record presence · all reporting utilities`],['NFIP net payments',money(r.nfip_total_net_payment_usd),`${fmt(r.nfip_recorded_claims)} recorded claims · nominal USD`]].map(([label,value,note])=>`<div class="card"><small>${esc(label)}</small><strong>${esc(value)}</strong><p>${esc(note)}</p></div>`).join('');
    drawMap(rows);
    $('timelineTitle').textContent=`${r.county_name}, hour by hour`;$('timelines').replaceChildren();
    chart($('timelines'),hours,'precipitation_in','Hourly precipitation (inches)','#5f8f9a',true);
    chart($('timelines'),hours,'wind_gusts_10m_mph','Hourly peak wind gust (mph)','#b5452a');
    chart($('timelines'),hours,'outage_customers_mean_observed','Customers out (mean of observed snapshots)','#1f6f78');
    $('timelineNote').textContent='Horizontal labels show local month-day and hour. Missing outage hours are gaps; partial hours use only available snapshots. Hover marks for values and sample counts. Weather: organizer-supplied Open-Meteo/ERA5. Outages: DOE/ORNL EAGLE-I v4. Recovery may continue beyond this window.'+(storm.value==='Hurricane_Harvey_2017'?' EAGLE-I Harvey coverage is incomplete in several counties; see the Harvey supplement below for daily ZIP-based counts.':'');
    $('summaryCaption').textContent=`${d.storms[storm.value].name} (${d.storms[storm.value].year}) · five county–storm records`;
    $('summary').innerHTML=rows.map(row=>`<tr class="${row.county_fips===county.value?'active':''}"><td><button data-fips="${row.county_fips}">${esc(row.county_name)}</button></td><td>${fmt(row.total_precipitation_in,2)}</td><td>${fmt(row.peak_wind_gust_mph,1)}</td><td>${fmt(row.outage_peak_customers_observed)}</td><td>${fmt(row.outage_record_presence_fraction*100,1)}%</td><td>${fmt(row.nfip_recorded_claims)}</td><td>${money(row.nfip_total_net_payment_usd)}</td></tr>`).join('');
    $('summary').querySelectorAll('button').forEach(b=>b.onclick=()=>{county.value=b.dataset.fips;render();});
    renderHarvey();
    $('associations').innerHTML=d.associations.filter(a=>a.storm_event===storm.value).map(a=>`<p>${a.x==='peak_wind_gust_mph'?'Peak gust vs. peak observed county outages':'Total rainfall vs. nominal NFIP net payments'}: Pearson r = <strong>${fmt(a.pearson_r,3)}</strong>, n = ${a.n_county_storm_pairs}.</p>`).join('');
  }
  function renderEvidence(){
    const R=d.reports,names=Object.fromEntries(R.list.map(r=>[r.report_id,r.publisher])),total=R.list.length;
    const issues=R.consensus.filter(c=>!['outage_scale','restoration_speed'].includes(c.issue_category));
    const top=issues[0];
    $('reportsIntro').textContent=`${total} official sources (PUCT investigation, CenterPoint's report to the PUCT, NWS impact summary, City of Houston filing, and the Governor's Harvey commission). Every bar below counts reports with a page-cited quote; quotes are checked against the report text at build time. Top issue: ${top.issue_label.toLowerCase()} (${top.reports_raising} of ${total} reports${top.raised_in_both_storms?', in both Harvey and Beryl':''}).`;
    $('consensus').innerHTML=issues.map(c=>`<div class="issue"><div><strong>${esc(c.issue_label)}</strong><small>${esc(c.report_ids.split(';').map(id=>names[id]).join(' · '))}${c.raised_in_both_storms?' · both storms':''}${c.utility_and_regulator_agree?' · utility and regulator agree':''}</small></div><div class="bar" role="img" aria-label="${c.reports_raising} of ${total} reports"><i style="width:${100*c.reports_raising/total}%"></i><span>${c.reports_raising} of ${total} reports</span></div></div>`).join('');
    $('findings').innerHTML=R.findings.map(f=>`<tr><td>${esc(f.issue_category.replaceAll('_',' '))}</td><td><a href="${esc(f.source_url)}" target="_blank" rel="noopener">${esc(names[f.report_id])}</a></td><td>${esc(f.page)}</td><td>“${esc(f.quote)}”</td></tr>`).join('');
    const verdicts={agree_within_10pct:'Agree (±10%)',disagree:'Disagree',unit_mismatch:'Unit mismatch',different_geography:'Different geography',not_comparable:'Outside data window'};
    const num=(v,u)=>v===null||v===undefined?'—':`${fmt(v)} ${esc(u)}`;
    $('discTable').innerHTML=R.discrepancies.map(r=>`<tr><td>${esc(r.topic)}</td><td>${num(r.value_a,r.unit_a)}<br><small>${esc(r.source_a)}</small></td><td>${num(r.value_b,r.unit_b)}<br><small>${esc(r.source_b)}</small></td><td>${r.ratio_b_over_a===null?'—':fmt(r.ratio_b_over_a,2)+'×'}</td><td><span class="verdict ${r.verdict}">${verdicts[r.verdict]}</span></td><td>${esc(r.note)}</td></tr>`).join('');
    const when=(t,u)=>t===null?'Not reached':`${t} ${u}`;
    $('restTable').innerHTML=d.restoration.map(r=>`<tr><td>${esc(d.storms[r.storm_event].name)}</td><td>${esc(r.county_name)}</td><td>${fmt(r.peak_outages)}</td><td>${esc(String(r.peak_at).slice(0,16).replace('T',' '))}</td><td>${when(r.to_half,r.time_unit)}</td><td>${when(r.to_tenth,r.time_unit)}</td><td>${fmt(r.outages_at_data_end)} (${esc(String(r.data_ends).slice(0,10))})</td><td>${r.source==='harvey_zip_file_daily'?'ZIP file, daily':'EAGLE-I, hourly'}</td></tr>`).join('');
  }
  function baseMap(id,labels=true){
    const map=L.map(id,{zoomControl:false,attributionControl:true,scrollWheelZoom:true,minZoom:7,maxZoom:16}).setView([29.76,-95.37],9);
    const esri='https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/';
    L.tileLayer(esri+'World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}',{maxZoom:16,attribution:'Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors'}).addTo(map);
    if(labels)L.tileLayer(esri+'World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}',{maxZoom:16,pane:'shadowPane'}).addTo(map);
    L.geoJSON(d.counties,{style:{color:'#22313a',weight:1.5,opacity:.55,fill:false},interactive:false}).addTo(map);
    return map;
  }
  function renderStaging(){
    const M=d.staging.meta;
    if(!window.L){$('stagingIntro').textContent='The map library did not load. Reload the page to try again.';return;}
    const hav=(a,b,c,e)=>{const r=Math.PI/180,p1=a*r,p2=c*r,dl=(c-a)*r,dn=(e-b)*r;return 6371.0088*2*Math.asin(Math.min(1,Math.sqrt(Math.sin(dl/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dn/2)**2)));};
    const floodClaims=d.staging.points.filter(p=>p.scenario==='flood').reduce((a,p)=>a+p.weight,0);
    const kind=x=>x.site_id.startsWith('new')?'new':x.unofficial?'unofficial':x.site_type==='recovery_center'?'recovery':x.site_type==='utility_service_center'?'utility':'shelter';
    const kindLabel={shelter:'Official shelter',recovery:'FEMA recovery center',utility:'Utility service center',unofficial:'Unofficial site',new:'Your site'};
    const officialMix=s=>{const n=t=>s.sites.filter(x=>kind(x)===t).length;return `${n('shelter')} shelters run by the City of Houston, Harris County or the Red Cross, and ${n('recovery')} FEMA disaster recovery centers`;};
    const copy={
      relief:{intro:s=>`Where should relief hubs go? The map starts with the ${s.baseline_sites} official Harvey sites: ${officialMix(s)}. Need is weighted half by power-outage burden and half by flood claims across ${fmt(s.demand_points)} locations.`,
              point:p=>`${p.label}: ${fmt(p.weight,0)} need points`},
      power:{intro:s=>`Where should utility crews be based? The map starts with ${s.baseline_sites} of CenterPoint's 13 Houston Electric service centers, from its October 2017 list (one could not be located precisely). Demand is customer-days without power across ${fmt(s.demand_points)} Harvey ZIP codes. The PUCT found Beryl staging sites "farther outside of the greater Houston area" lengthened crew travel.`,
              point:p=>`${p.label}: ${fmt(p.weight)} customer-days without power`},
      flood:{intro:s=>`Where should flood shelters and relief points go? The map starts with the ${s.baseline_sites} official Harvey sites: ${officialMix(s)}. Demand is ${fmt(floodClaims)} Harvey flood insurance claims, grouped into ${fmt(s.demand_points)} map cells.`,
              point:p=>`${p.label}: ${fmt(p.weight)} flood claims`}
    };
    const shortName=n=>n.split(' (')[0].replace(' service center','').replace(' Convention Center','').replace(' / Magnolia Park','').replace(' / Channelview / Berry','');
    const plans={};
    const resetPlan=k=>{plans[k]=d.staging.scenarios[k].sites.map(s=>({...s,label:shortName(s.name),moved:false}));};
    M.order.forEach(resetPlan);
    let key='relief',added=0,placing=false;
    try{const saved=localStorage.getItem('stagingTab');if(M.order.includes(saved))key=saved;}catch(e){}
    const map=baseMap('stagingMap'),subLayer=L.layerGroup(),demandLayer=L.layerGroup().addTo(map),siteLayer=L.layerGroup().addTo(map);
    // HIFLD substations: context only, not counted in trip times.
    let subsOn=false;
    for(const s of d.staging.substations||[])L.circleMarker([s.latitude,s.longitude],{radius:3.2,color:'#5b3f8f',weight:1.2,fillColor:'#fff',fillOpacity:1})
      .bindTooltip(`<strong>${esc(s.name)} ${esc(s.type)}</strong><br>${s.max_kv?esc(String(s.max_kv))+' kV, ':''}${esc(s.status)}${s.city?'<br>'+esc(s.city):''}<br><small>HIFLD (DHS) substation layer</small>`).addTo(subLayer);
    const setSubs=on=>{subsOn=on;if(on&&key==='power')subLayer.addTo(map);else map.removeLayer(subLayer);const b=$('toggleSubstations');b.setAttribute('aria-pressed',String(on));b.textContent=on?`Hide substations (${fmt((d.staging.substations||[]).length)})`:`Show substations (${fmt((d.staging.substations||[]).length)})`;};
    // Labels only on sites the user has touched; the many official sites show their name on hover.
    const icon=(cls,text)=>L.divIcon({className:'site-pin '+cls,html:`<span></span>${text?`<b>${esc(text)}</b>`:''}`,iconSize:[16,16],iconAnchor:[8,8]});
    const pts=()=>d.staging.points.filter(p=>p.scenario===key);
    const access=list=>{if(!list.length)return null;let w=0,t=0;for(const z of pts()){const km=Math.min(...list.map(x=>hav(z.latitude,z.longitude,x.lat,x.lon)));w+=z.weight;t+=z.weight*km;}const km=t/w*M.road_circuity;return {km,min:km/M.storm_speed_kmh*60};};
    function fit(){const s=d.staging.scenarios[key],b=L.latLngBounds([...pts().map(p=>[p.latitude,p.longitude]),...s.sites.map(x=>[x.lat,x.lon])]);map.fitBounds(b.pad(0.04));}
    function drawDemand(){
      demandLayer.clearLayers();
      const list=pts(),maxW=Math.max(...list.map(p=>p.weight)),color=key==='flood'?'#3f7f8c':key==='power'?'#1f6f78':'#2f5866';
      for(const p of list)L.circleMarker([p.latitude,p.longitude],{radius:2.5+11*Math.sqrt(p.weight/maxW),color,weight:0,fillColor:color,fillOpacity:.38,interactive:true,bubblingMouseEvents:true})
        .bindTooltip(`${copy[key].point(p)}<br>${fmt(p.road_km_to_nearest_site,1)} road km to today's nearest site`,{direction:'top'}).addTo(demandLayer);
      const b=d.staging.scenarios[key].best_candidate;
      L.marker([b.latitude,b.longitude],{icon:L.divIcon({className:'best-pin',html:'<span>★</span><b>best single addition</b>',iconSize:[20,20],iconAnchor:[10,10]}),interactive:false,keyboard:false}).addTo(demandLayer);
    }
    function drawSites(){
      siteLayer.clearLayers();
      plans[key].forEach((x,i)=>{
        const k=kind(x),cls=k+(x.moved?' moved':''),few=plans[key].length<=6;
        const m=L.marker([x.lat,x.lon],{icon:icon(cls,few||k==='new'||x.moved?x.label:''),draggable:true,riseOnHover:true,autoPan:true}).addTo(siteLayer);
        m.bindTooltip(`<strong>${esc(x.name||x.label)}</strong><br>${kindLabel[k]}${x.operator?', '+esc(x.operator):''}${x.moved?'<br>Moved from its real location':''}<br><small>Drag to move, double-click to remove</small>`,{direction:'top',offset:[0,-8]});
        m.on('drag',e=>{const ll=e.target.getLatLng();x.lat=ll.lat;x.lon=ll.lng;report();});
        m.on('dragend',()=>{x.moved=!x.site_id.startsWith('new');drawSites();report();});
        m.on('dblclick',e=>{L.DomEvent.stop(e);plans[key].splice(i,1);drawSites();report();});
      });
    }
    function report(){
      const s=d.staging.scenarios[key],plan=plans[key],base=access(s.sites),now=access(plan),b=s.best_candidate;
      let html;
      if(!now)html=`<h3>No sites in this plan</h3><p>Turn on Place sites and click the map, or reset to today's sites.</p>`;
      else{
        const diff=base.min-now.min,changed=plan.length!==s.sites.length||plan.some(x=>x.moved||x.unofficial||x.site_id.startsWith('new'));
        html=changed?`<h3>Your plan: ${fmt(now.min,0)} min average trip</h3><p>${diff>=0?`${fmt(diff,1)} min faster`:`${fmt(-diff,1)} min slower`} than today's ${fmt(base.min,0)} min with ${plan.length} site${plan.length===1?'':'s'} (${fmt(Math.abs(100*(1-now.km/base.km)),1)}% ${diff>=0?'less':'more'} driving).</p>`
          :`<h3>Today: ${fmt(base.min,0)} min average trip</h3><p>Adding the best single site (★) brings that to ${fmt(b.weighted_travel_minutes,0)} min: ${fmt(b.minutes_saved,1)} min faster, ${fmt(b.pct_travel_reduction,1)}% less driving.</p>`;
      }
      if(key==='power'){const ev=s.evidence;html+=`<p style="margin-top:12px"><strong>What else speeds restoration?</strong> In Harvey, restoration pace across ${ev.n_zips_timed} ZIPs tracked flood damage, road access and communication more than distance to a service center (r = ${fmt(ev.r_distance_vs_days_to_half,2)}). See <a href="#/outages">Outages &amp; recommendations</a>.</p>`;}
      if(key==='flood')html+=`<p style="margin-top:12px"><strong>Why it matters:</strong> in Harvey, floodwaters forced responders to move their staging farther from Houston (Eye of the Storm, p.100). Sites near the densest claims keep relief within reach.</p>`;
      if(key==='relief')html+=`<p style="margin-top:12px"><strong>One site, two needs:</strong> hubs here serve both outage and flood demand, so each one reaches more households.</p>`;
      $('stagingResult').innerHTML=html;
      $('siteList').innerHTML=plan.map((x,i)=>`<li><span class="swatch ${kind(x)}${x.moved?' moved':''}"></span><span class="site-name">${esc(x.label)}<small>${kindLabel[kind(x)]}${x.moved?', moved':''}</small></span><button type="button" data-remove="${i}" aria-label="Remove ${esc(x.label)}">Remove</button></li>`).join('');
      const uo=s.unofficial_sites||[],on=plan.some(x=>x.unofficial);
      $('toggleUnofficial').hidden=!uo.length;
      $('toggleUnofficial').textContent=on?`Remove unofficial sites (${uo.length})`:`Add unofficial sites (${uo.length})`;
      $('toggleUnofficial').setAttribute('aria-pressed',String(on));
      $('unofficialInfo').hidden=!uo.length;
      if(uo.length){
        const w=s.with_unofficial;
        $('unofficialInfo').innerHTML=`<h3>What makes a site unofficial</h3><p>These ${uo.length} places took people in during Harvey, but no city, county, Red Cross or FEMA list designated them. They were opened by businesses, churches and volunteers, so their capacity, supplies, medical support and hours were not coordinated with emergency managers, and they could close without notice. That is why the plan starts without them.</p><p>Adding all ${uo.length} to today's official sites brings the average trip from ${fmt(s.baseline_weighted_travel_minutes,0)} to ${fmt(w.weighted_travel_minutes,0)} min. Formalizing the best-placed ones before the next storm would put that gain on the official map.</p><ul>${uo.map(x=>`<li><strong>${esc(x.name.split(' (')[0])}</strong>, ${esc(x.operator)}${x.note?'. '+esc(x.note):''} <a href="${x.source.startsWith('http')?esc(x.source):'#/reports'}" ${x.source.startsWith('http')?'target="_blank" rel="noopener"':''}>Source</a></li>`).join('')}</ul>`;
      }
      $('siteList').querySelectorAll('[data-remove]').forEach(btn=>btn.onclick=()=>{plans[key].splice(+btn.dataset.remove,1);drawSites();report();});
    }
    function show(){
      const s=d.staging.scenarios[key];
      $('stagingIntro').textContent=copy[key].intro(s)+' Move mode: drag the map to pan, scroll or use + and − to zoom, and drag a site to move it. Turn on Place sites to add sites by clicking the map. Double-click a site to remove it.';
      $('stagingNote').textContent=`How this is calculated: trip = straight-line distance × ${M.road_circuity} for roads, at ${M.storm_speed_kmh} km/h storm-period driving, weighted by ${s.demand}. Site lists come from Harvey-era city, county, Red Cross and FEMA announcements as reported in local news; every site's status, operator and source are in the relief sites download on the Data & sources page. Live traffic and road-closure feeds would sharpen the travel times.`;
      M.order.forEach(k=>{const t=$('tab-'+k);t.setAttribute('aria-selected',String(k===key));t.tabIndex=k===key?0:-1;});
      $('toggleSubstations').hidden=key!=='power';$('substationNote').hidden=key!=='power';setSubs(subsOn);
      drawDemand();drawSites();report();fit();
    }
    function setMode(on){placing=on;const b=$('placeMode');b.setAttribute('aria-pressed',String(on));b.textContent=on?'Placing: click map to add':'Place sites';$('stagingMap').classList.toggle('placing',on);$('moveMode').setAttribute('aria-pressed',String(!on));}
    map.on('click',e=>{if(!placing)return;added++;plans[key].push({site_id:'new'+added,name:`New site ${added}`,label:`New site ${added}`,lat:e.latlng.lat,lon:e.latlng.lng,moved:false});drawSites();report();});
    map.doubleClickZoom.disable();
    $('placeMode').onclick=()=>setMode(!placing);$('moveMode').onclick=()=>setMode(false);
    document.addEventListener('keydown',e=>{if(e.key==='Escape'&&placing)setMode(false);});
    $('zoomIn').onclick=()=>map.zoomIn();$('zoomOut').onclick=()=>map.zoomOut();$('resetView').onclick=fit;
    $('resetSites').onclick=()=>{resetPlan(key);drawSites();report();};
    $('toggleSubstations').onclick=()=>setSubs(!subsOn);
    $('toggleUnofficial').onclick=()=>{
      const uo=d.staging.scenarios[key].unofficial_sites||[];
      if(plans[key].some(x=>x.unofficial))plans[key]=plans[key].filter(x=>!x.unofficial);
      else plans[key].push(...uo.map(s=>({...s,label:shortName(s.name),moved:false,unofficial:true})));
      drawSites();report();
    };
    $('resetPositions').onclick=()=>{const added_=plans[key].filter(x=>x.site_id.startsWith('new')||x.unofficial).map(x=>x.unofficial?{...(d.staging.scenarios[key].unofficial_sites.find(u=>u.site_id===x.site_id)),label:x.label,moved:false,unofficial:true}:x);plans[key]=[...d.staging.scenarios[key].sites.map(s=>({...s,label:shortName(s.name),moved:false})),...added_];drawSites();report();};
    $('addBest').onclick=()=>{const b=d.staging.scenarios[key].best_candidate;added++;plans[key].push({site_id:'new'+added,name:'Best single addition',label:'Best single addition',lat:b.latitude,lon:b.longitude,moved:false});drawSites();report();};
    M.order.forEach((k,i)=>{
      const t=$('tab-'+k);
      t.onclick=()=>{key=k;try{localStorage.setItem('stagingTab',k);}catch(e){}show();};
      t.onkeydown=e=>{if(e.key==='ArrowRight'||e.key==='ArrowLeft'){const n=M.order[(i+(e.key==='ArrowRight'?1:M.order.length-1))%M.order.length];$('tab-'+n).focus();$('tab-'+n).click();}};
    });
    show();
    window.refitStaging=()=>{map.invalidateSize();fit();};
  }
  function renderDrivers(){
    const D=d.drivers,c=Object.fromEntries(D.correlations.map(x=>[x.trait,x])),fl=c.flood_claims_per_1k_customers;
    $('driversLead').textContent=`Areas where power stayed out longest had ${fmt(fl.high_over_low,1)}× the flood insurance claims of areas restored fastest: ${fmt(fl.high_downtime_median,0)} versus ${fmt(fl.low_downtime_median,0)} claims per 1,000 customers. Distance to a service center made no difference.`;
    const unit={flood_claims_per_1k_customers:v=>fmt(v,1),share_claims_high_risk_zone:v=>fmt(100*v,0)+'%',median_water_depth:v=>fmt(v,2),road_km_to_service_center:v=>fmt(v,1)+' km',customers:v=>fmt(v),latitude:v=>fmt(v,2)+'°N'};
    $('driversTable').innerHTML=D.correlations.map(x=>`<tr class="trait-row" data-trait="${x.trait}" tabindex="0" role="button" aria-pressed="false" title="Show this trait on the map"><td>${esc(x.label)}<small class="row-hint">Show on map</small></td><td>${unit[x.trait](x.low_downtime_median)}</td><td>${unit[x.trait](x.high_downtime_median)}</td><td><span class="rbar" style="--r:${Math.abs(x.spearman_r||0)}"><i class="${(x.spearman_r||0)<0?'neg':''}"></i></span>${x.spearman_r===null?'Unknown':(x.spearman_r>=0.005?'+':x.spearman_r<=-0.005?'−':'')+Math.abs(x.spearman_r).toFixed(2)}</td></tr>`).join('');
    $('hotspotList').innerHTML=D.hotspots.slice(0,5).map(h=>`<li><strong>${esc(h.label)}</strong> <span>${esc(h.zips.replaceAll(';',', '))}</span><small>${fmt(h.median_downtime,2)} days out per customer, ${fmt(h.median_flood_claims_per_1k,0)} flood claims per 1,000 customers</small></li>`).join('');
    const names=Object.fromEntries(d.reports.list.map(r=>[r.report_id,r.publisher])),fby=Object.fromEntries(d.reports.findings.map(f=>[f.finding_id,f]));
    const zipById=Object.fromEntries(D.zips.map(z=>[z.zip_code,z]));
    const areaButtons=r=>r.target_kind==='counties'
      ? `<p class="note">Beryl data supports county priorities only; specific ZIP codes need circuit-level outage and canopy data.</p>`
      : `<div class="rec-zips" aria-label="Target ZIP codes">${r.target_ids.split(';').map(id=>{const z=zipById[id];return `<button type="button" class="rec-zip" data-rec-id="${r.id}" data-zip="${esc(id)}" title="Locate ZIP ${esc(id)} on the map">${esc(id)}${z?.area_name?' - '+esc(z.area_name):''}</button>`;}).join('')}</div>`;
    $('recs').innerHTML=D.recommendations.map(r=>`<li data-rec="${r.id}"><h3>${esc(r.title)}</h3><p class="strength">${esc(r.strength)}</p><p>${esc(r.evidence)}</p><p><strong>Do this:</strong> ${esc(r.action)}</p><p class="where"><strong>Where:</strong> ${r.target_kind==='counties'?esc(r.target_places):'The '+r.target_count+' ZIP codes listed below.'} <button type="button" class="show-rec" data-show="${r.id}">Show on map</button></p>${areaButtons(r)}<p class="cites">Sources: ${r.findings.split(';').map(id=>fby[id]).filter(Boolean).map(f=>`<a href="${esc(f.source_url)}" target="_blank" rel="noopener" title="${esc(f.quote)}">${esc(names[f.report_id])} p.${esc(f.page)}</a>`).join(', ')}</p></li>`).join('');
    let recMap=null,recLayer=null,recSel=D.recommendations[0].id;
    const recShapes=new Map();
    const zipTip=z=>`<strong>ZIP ${esc(z.zip_code)}${z.area_name?' ('+esc(z.area_name)+')':''}</strong><br>${fmt(z.downtime_customer_days_per_customer,2)} days out per customer<br>${fmt(z.flood_claims_per_1k_customers,0)} flood claims per 1,000 customers<br>${fmt(z.customers)} customers`;
    function drawRec(){
      const r=D.recommendations.find(x=>x.id===recSel);
      document.querySelectorAll('.rec-zip').forEach(b=>b.setAttribute('aria-pressed','false'));
      document.querySelectorAll('#recs li').forEach(li=>li.classList.toggle('selected',li.dataset.rec===recSel));
      document.querySelectorAll('.show-rec').forEach(b=>{const on=b.dataset.show===recSel;b.textContent=on?'Shown on map':'Show on map';b.setAttribute('aria-pressed',String(on));});
      $('recMapTitle').textContent=`${D.recommendations.indexOf(r)+1}. ${r.title}`;
      $('recMapRule').textContent='How these areas were chosen: '+r.target_rule;
      if(!window.L)return;
      if(!recMap){if($('recMap').offsetWidth===0)return;recMap=baseMap('recMap',false);recLayer=L.layerGroup().addTo(recMap);}
      recLayer.clearLayers();recShapes.clear();
      const ids=new Set(r.target_ids.split(';'));
      if(r.target_kind==='counties'){
        const hours=r.county_hours||{},max=Math.max(...Object.values(hours));
        const geo=L.geoJSON(d.counties,{style:f=>{const on=ids.has(f.properties.id);return {color:on?'#b5452a':'#ffffff',weight:on?3:1.5,fillColor:on?'#b5452a':'#cfd6d8',fillOpacity:on?0.25+0.45*(hours[f.properties.id]||0)/max:0.35};}})
          .eachLayer(l=>{const id=l.feature.properties.id,h=hours[id];l.bindTooltip(`<strong>${esc(l.feature.properties.NAME)}</strong><br>${h!==undefined?h+' hours to halve Beryl outages':'Outside the five study counties'}`,{sticky:true});}).addTo(recLayer);
        d.counties.features.filter(f=>hours[f.properties.id]!==undefined).forEach(f=>{const c=L.geoJSON(f).getBounds().getCenter();
          L.marker(c,{interactive:false,keyboard:false,icon:L.divIcon({className:'county-label',html:`<div class="cl"><b>${esc(f.properties.NAME)}</b><span>${hours[f.properties.id]} h</span></div>`,iconSize:null})}).addTo(recLayer);});
        recMap.fitBounds(geo.getBounds().pad(0.02));
      }else{
        for(const z of D.zips){if(ids.has(z.zip_code))continue;L.circleMarker([z.latitude,z.longitude],{radius:3,weight:0,fillColor:'#8fa3aa',fillOpacity:.45,interactive:false}).addTo(recLayer);}
        const chosen=D.zips.filter(z=>ids.has(z.zip_code));
        for(const z of chosen){
          const rings=D.zip_boundaries?.[z.zip_code];
          const shape=rings?L.polygon(rings,{color:'#b5452a',weight:2,fillColor:'#b5452a',fillOpacity:.22,fillRule:'evenodd'})
            :L.circleMarker([z.latitude,z.longitude],{radius:8,color:'#b5452a',fillOpacity:.8});
          shape.bindTooltip(zipTip(z)).bindPopup(zipTip(z)).addTo(recLayer);
          recShapes.set(z.zip_code,shape);
          L.marker([z.latitude,z.longitude],{interactive:false,keyboard:false,icon:L.divIcon({className:'rec-label',html:`<span>${esc(z.zip_code)}</span>`,iconSize:null})}).addTo(recLayer);
        }
        const bounds=L.latLngBounds([]);
        recShapes.forEach(shape=>shape.getBounds?bounds.extend(shape.getBounds()):bounds.extend(shape.getLatLng()));
        if(bounds.isValid())recMap.fitBounds(bounds.pad(.08),{maxZoom:11});
      }
    }
    document.querySelectorAll('.show-rec').forEach(b=>b.onclick=()=>{recSel=b.dataset.show;drawRec();if(window.innerWidth<900)$('recMap').scrollIntoView({behavior:'smooth',block:'center'});});
    document.querySelectorAll('.rec-zip').forEach(b=>b.onclick=()=>{
      recSel=b.dataset.recId;drawRec();
      document.querySelectorAll('.rec-zip').forEach(btn=>btn.setAttribute('aria-pressed',String(btn===b)));
      const shape=recShapes.get(b.dataset.zip);
      if(shape){if(shape.getBounds)recMap.fitBounds(shape.getBounds().pad(.12),{maxZoom:12});else recMap.setView(shape.getLatLng(),12);shape.openPopup();}
      if(window.innerWidth<900)$('recMap').scrollIntoView({behavior:'smooth',block:'center'});
    });
    drawRec();
    window.refitRecMap=()=>{if(recMap)recMap.invalidateSize();drawRec();};
    if(!window.L)return;
    const map=baseMap('driversMap'),colors=['#9cc3c8','#5f9aa3','#d08a3c','#b5452a'];
    map.fitBounds(L.latLngBounds(D.zips.map(z=>[z.latitude,z.longitude])).pad(0.03));
    const dots=L.layerGroup().addTo(map),labels=L.layerGroup().addTo(map);
    D.hotspots.slice(0,5).forEach((h,i)=>L.marker([h.latitude,h.longitude],{icon:L.divIcon({className:'hot-label',html:`<b>${i+1}</b> ${esc(h.label)}`,iconSize:null}),interactive:false}).addTo(labels));
    const defaultLegend=$('driversLegend').innerHTML;
    const tip=(z,extra='')=>`ZIP ${esc(z.zip_code)}${z.area_name?' ('+esc(z.area_name)+')':''}<br>${fmt(z.downtime_customer_days_per_customer,2)} days out per customer${extra}`;
    let selected=null;
    // Default: every ZIP colored by outage-length quarter. With a trait selected: only the two quarters the row compares, sized by the trait.
    function drawDots(){
      dots.clearLayers();
      document.querySelectorAll('.trait-row').forEach(tr=>{const on=tr.dataset.trait===selected;tr.classList.toggle('active',on);tr.setAttribute('aria-pressed',String(on));tr.querySelector('.row-hint').textContent=on?'Shown on map, click to clear':'Show on map';});
      if(!selected){
        for(const z of D.zips)L.circleMarker([z.latitude,z.longitude],{radius:z.small_denominator?3:6,color:'#fff',weight:1,fillColor:colors[z.downtime_quartile-1],fillOpacity:.9})
          .bindTooltip(tip(z,`<br>${fmt(z.flood_claims_per_1k_customers,0)} flood claims per 1,000 customers`)).addTo(dots);
        $('driversLegend').innerHTML=defaultLegend;labels.addTo(map);return;
      }
      map.removeLayer(labels);
      const x=c[selected],vals=D.zips.filter(z=>!z.small_denominator).map(z=>z[selected]).sort((a,b)=>a-b);
      const rank=v=>{let i=0;while(i<vals.length&&vals[i]<v)i++;return i/Math.max(1,vals.length-1);};
      const compared=D.zips.filter(z=>!z.small_denominator&&(z.downtime_quartile===1||z.downtime_quartile===4));
      for(const z of D.zips){if(compared.includes(z))continue;L.circleMarker([z.latitude,z.longitude],{radius:2.5,weight:0,fillColor:'#9aa9ae',fillOpacity:.35,interactive:false}).addTo(dots);}
      // Draw small values first so large dots sit underneath and stay visible.
      for(const z of compared.sort((a,b)=>b[selected]-a[selected])){
        const slow=z.downtime_quartile===4;
        L.circleMarker([z.latitude,z.longitude],{radius:3+11*rank(z[selected]),color:'#fff',weight:1.2,fillColor:slow?'#b5452a':'#5f9aa3',fillOpacity:.85})
          .bindTooltip(tip(z,`<br><strong>${esc(x.label)}: ${unit[selected](z[selected])}</strong><br>${slow?'Slowest-restored quarter':'Fastest-restored quarter'}`)).addTo(dots);
      }
      $('driversLegend').innerHTML=`<span><i style="background:#b5452a"></i>Slowest-restored quarter (median ${unit[selected](x.high_downtime_median)})</span><span><i style="background:#5f9aa3"></i>Fastest quarter (median ${unit[selected](x.low_downtime_median)})</span><span>Dot size: ${esc(x.label.toLowerCase())}</span><span><i style="background:#9aa9ae;opacity:.5"></i>Other ZIPs</span>`;
    }
    const pick=t=>{selected=selected===t?null:t;drawDots();};
    document.querySelectorAll('.trait-row').forEach(tr=>{tr.onclick=()=>pick(tr.dataset.trait);tr.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();pick(tr.dataset.trait);}};});
    drawDots();
    map.fitBounds(L.latLngBounds(D.zips.map(z=>[z.latitude,z.longitude])).pad(0.03));
    window.refitDrivers=()=>{map.invalidateSize();map.fitBounds(L.latLngBounds(D.zips.map(z=>[z.latitude,z.longitude])).pad(0.03));};
  }
  function renderHero(){
    const svg=$('heroCurve'),byTime={};
    d.hourly.filter(h=>h.storm_event==='Hurricane_Beryl_2024').forEach(h=>{(byTime[h.time_utc]??=[]).push(h);});
    let pts=Object.entries(byTime).sort().map(([t,rows])=>({t:new Date(t),local:rows[0].time_local,v:rows.length===5&&rows.every(r=>r.outage_customers_mean_observed!==null)?rows.reduce((a,r)=>a+r.outage_customers_mean_observed,0):null})).filter(p=>p.v!==null);
    // Drop one-hour source dropouts: a point far below both neighbours.
    pts=pts.filter((p,i)=>!(i>0&&i<pts.length-1&&p.v<0.9*pts[i-1].v&&p.v<0.9*pts[i+1].v));
    const W=1200,H=380,L=70,R=1180,T=30,B=330,t0=+pts[0].t,t1=+pts.at(-1).t,max=Math.max(...pts.map(p=>p.v));
    const x=t=>L+(t-t0)/(t1-t0)*(R-L),y=v=>B-v/(max*1.08)*(B-T),at=s=>+new Date(s);
    [0,1e6,2e6].forEach(v=>{svg.append(create('line',{x1:L,x2:R,y1:y(v),y2:y(v),class:'grid'}));svg.append(create('text',{x:L-10,y:y(v)+4,'text-anchor':'end',class:'tick'},v?`${v/1e6}M`:'0'));});
    for(let day=new Date('2024-07-05T05:00:00Z');+day<=t1;day=new Date(+day+864e5)){const xx=x(+day);svg.append(create('text',{x:xx,y:B+24,class:'tick'},day.toLocaleDateString('en-US',{month:'short',day:'numeric',timeZone:'America/Chicago'})));svg.append(create('line',{x1:xx,x2:xx,y1:B,y2:B+6,class:'grid'}));}
    // The no-information window: landfall to the first replacement map (PUCT p.37).
    svg.append(create('rect',{x:x(at('2024-07-08T09:00:00Z')),y:T,width:x(at('2024-07-10T05:00:00Z'))-x(at('2024-07-08T09:00:00Z')),height:B-T,class:'blackout'}));
    const area='M'+x(t0)+','+B+pts.map(p=>'L'+x(+p.t)+','+y(p.v)).join('')+'L'+x(t1)+','+B+'Z';
    svg.append(create('path',{d:area,class:'curve-fill'}));
    svg.append(create('path',{d:'M'+pts.map(p=>x(+p.t)+','+y(p.v)).join('L'),class:'curve'}));
    const peak=pts.reduce((a,p)=>p.v>a.v?p:a),last=pts.at(-1);
    const note=(px,py,lines,anchor='start',dy=0)=>{svg.append(create('circle',{cx:px,cy:py,r:5,class:'pin'}));lines.forEach((l,i)=>svg.append(create('text',{x:px+(anchor==='end'?-12:12),y:py+dy+i*17,'text-anchor':anchor,class:i?'note-q':'note-h'},l)));};
    note(x(+peak.t),y(peak.v),[`Peak: ${fmt(peak.v/1e6,2)} million out`,new Date(peak.t).toLocaleString('en-US',{hour:'numeric',timeZone:'America/Chicago'})+' on Jul 8, the day of landfall'],'end',4);
    const mid=x(at('2024-07-09T05:00:00Z'));
    svg.append(create('text',{x:mid,y:B-62,'text-anchor':'middle',class:'note-h'},'No working outage map'));
    svg.append(create('text',{x:mid,y:B-44,'text-anchor':'middle',class:'note-q'},'“over 2.2 million CenterPoint customers lacked'));
    svg.append(create('text',{x:mid,y:B-27,'text-anchor':'middle',class:'note-q'},'independent access to information” (p.37)'));
    const sp=pts.find(p=>+p.t>=at('2024-07-10T17:00:00Z'));
    note(x(+sp.t),y(sp.v),['Crews staged far outside Houston','“longer transit times to worksites” (p.59)'],'start',-40);
    note(x(+last.t),y(last.v),[`${fmt(last.v/1e6,2)} million still out`,'when this record ends, Jul 12','Below 10,000 only on Jul 19 (p.15)'],'end',30);
  }
  renderHero();renderEvidence();renderStaging();renderDrivers();
  const pages=[...document.querySelectorAll('[data-nav]')].map(a=>({key:a.dataset.nav,label:a.textContent}));
  function route(){
    let key=(location.hash.match(/^#\/(\w+)/)||[])[1];
    if(!pages.some(p=>p.key===key)){
      // Old in-page links (e.g. #staging) still land on the right page.
      const target=location.hash.length>1?document.getElementById(location.hash.slice(1)):null;
      key=target?.closest('[data-page]')?.dataset.page.split(' ').pop()||'overview';
    }
    document.querySelectorAll('[data-page]').forEach(el=>{el.hidden=!el.dataset.page.split(' ').includes(key);});
    document.querySelectorAll('[data-nav]').forEach(a=>{if(a.dataset.nav===key)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
    const i=pages.findIndex(p=>p.key===key),prev=pages[i-1],next=pages[i+1];
    $('pager').innerHTML=(prev?`<a class="prev" href="#/${prev.key}"><small>Previous</small>${esc(prev.label)}</a>`:'<span></span>')+(next?`<a class="next" href="#/${next.key}"><small>Next</small>${esc(next.label)}</a>`:'');
    document.title=(key==='overview'?'':pages[i].label+' | ')+'Houston Storm Impact & Recovery';
    // Maps created while hidden need their size recalculated once shown.
    if(key==='whatif'&&window.refitStaging)window.refitStaging();
    if(key==='outages'&&window.refitDrivers)window.refitDrivers();
    if(key==='outages'&&window.refitRecMap)window.refitRecMap();
    if(key==='explorer'){if(window.refitCounty)window.refitCounty();else render();}
    window.scrollTo(0,0);
  }
  window.addEventListener('hashchange',route);route();
  $('centerpoint').innerHTML=d.centerpoint.map(r=>`<div class="milestone"><time>${esc(r.report_time_local.slice(0,16).replace('T',' '))} CDT</time><strong>${esc(r.source_phrase)}</strong><small>${r.metric==='customers_restored'?'Customers restored':'Restoration share'}</small><br><a href="${esc(r.source_url)}" target="_blank" rel="noopener">Official release index</a></div>`).join('');
  $('validation').textContent=`Build checks passed with documented limitations: ${fmt(d.validation.hourly_rows)} hourly rows, ${d.validation.county_storm_rows} county–storm summaries, ${fmt(d.validation.assigned_claims)} assigned NFIP records. ${fmt(d.validation.missing_outage_quarters)} expected outage quarter-hours have no usable customer count (including ${d.validation.blank_outage_count_rows} blank source count).`;
  $('warnings').innerHTML=d.validation.warnings.map(w=>`<li>${esc(w)}</li>`).join('');
  $('sources').innerHTML=d.sources.map(s=>`<div class="source"><strong>${esc(s.file)}</strong> · ${s.source_url?`<a href="${esc(s.source_url)}" target="_blank" rel="noopener">Source</a>`:'Upstream source not documented'}<br>${esc(s.provenance_status.replaceAll('_',' '))}${s.retrieved_at_utc?' · Retrieved '+esc(s.retrieved_at_utc):' · Original retrieval date unavailable'}<code>SHA-256 ${esc(s.sha256)}</code></div>`).join('');
  [storm,county,metric].forEach(el=>el.addEventListener('change',render));render();
})();
