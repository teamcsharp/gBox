param([int]$Seconds=20,[string]$OutputPath='C:\_tools\gBox\.work\stream-client-baseline.json')
Add-Type -AssemblyName System.Net.Http
Add-Type -ReferencedAssemblies System.Net.Http -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Net.Http;
public class GBoxStreamMeter {
  public static Dictionary<string,object> Measure(string url,string token,int seconds) {
    using (var c=new HttpClient()) {
      c.DefaultRequestHeaders.Authorization=new System.Net.Http.Headers.AuthenticationHeaderValue("Bearer",token);
      using(var r=c.GetAsync(url,HttpCompletionOption.ResponseHeadersRead).GetAwaiter().GetResult()) {
        r.EnsureSuccessStatusCode();
        using(var s=r.Content.ReadAsStreamAsync().GetAwaiter().GetResult()) {
          byte[] b=new byte[65536]; var times=new List<double>();
          var watch=Stopwatch.StartNew(); int previous=0,n; long bytes=0;
          while(watch.Elapsed.TotalSeconds<seconds && (n=s.Read(b,0,b.Length))>0) {
            bytes+=n;
            for(int i=0;i<n;i++) {
              if(previous==255 && b[i]==217) times.Add(watch.Elapsed.TotalSeconds);
              previous=b[i];
            }
          }
          double elapsed=watch.Elapsed.TotalSeconds; var gaps=new List<double>(); int slow=0;
          for(int i=1;i<times.Count;i++) { double d=(times[i]-times[i-1])*1000;gaps.Add(d); if(d>100)slow++; }
          gaps.Sort();
          return new Dictionary<string,object>{
            {"seconds",Math.Round(elapsed,3)},{"frames",times.Count},{"fps",Math.Round(times.Count/elapsed,2)},
            {"gap_p50_ms",Math.Round(gaps[(gaps.Count-1)/2],2)},
            {"gap_p95_ms",Math.Round(gaps[(int)((gaps.Count-1)*.95)],2)},
            {"gap_max_ms",Math.Round(gaps[gaps.Count-1],2)},{"gaps_over_100ms",slow},
            {"bandwidth_mbps",Math.Round(bytes*8/elapsed/1000000,2)}
          };
        }
      }
    }
  }
}
'@
$taskToken=(Get-Content -LiteralPath C:\_tools\gBox\system\gbox-data\api_token -Raw).Trim()
$taskHeaders=@{Authorization='Bearer '+$taskToken}
$taskBase='http://10.89.1.246:8765'
$taskSession=@(Invoke-RestMethod -Uri "$taskBase/api/sessions?include_ended=false" -Headers $taskHeaders -TimeoutSec 10)[0].session_id
$taskHealthBefore=Invoke-RestMethod -Uri "$taskBase/api/sessions/$taskSession/stream/health" -Headers $taskHeaders -TimeoutSec 10
$taskMeasure=[GBoxStreamMeter]::Measure("$taskBase/api/sessions/$taskSession/mjpeg",$taskToken,$Seconds)
$taskHealthAfter=Invoke-RestMethod -Uri "$taskBase/api/sessions/$taskSession/stream/health" -Headers $taskHeaders -TimeoutSec 10
$taskResult=@{at=[DateTime]::UtcNow.ToString('o');path='Spark to Windows HTTP MJPEG';session_id=$taskSession;measure=$taskMeasure;health_before=$taskHealthBefore;health_after=$taskHealthAfter}
$taskResult | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
$taskMeasure | ConvertTo-Json -Compress
