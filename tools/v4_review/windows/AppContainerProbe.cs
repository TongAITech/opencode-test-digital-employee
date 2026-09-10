using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;

// Isolated qualification fixture only. Never point this program at product/bank files.
internal static class AppContainerProbe {
    static readonly JavaScriptSerializer Json = new JavaScriptSerializer();
    static string Exe { get { return Process.GetCurrentProcess().MainModule.FileName; } }
    static string Q(string s) {
        var b=new StringBuilder("\""); int slashes=0;
        foreach(char c in s) { if(c=='\\'){slashes++;continue;} if(c=='\"'){b.Append('\\',slashes*2+1).Append(c);}else{b.Append('\\',slashes).Append(c);} slashes=0; }
        return b.Append('\\',slashes*2).Append('\"').ToString();
    }
    static string PSQ(string s) { return "'" + s.Replace("'", "''") + "'"; }
    static void Save(string path, object obj) { File.WriteAllText(path, Json.Serialize(obj), new UTF8Encoding(false)); }
    static Dictionary<string,object> Read(string path) { return Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(path)); }
    static bool B(Dictionary<string,object> d, string k) { return d.ContainsKey(k) && d[k] is bool && (bool)d[k]; }
    static Dictionary<string,object> D(Dictionary<string,object> d, string k) { return d[k] as Dictionary<string,object>; }
    static void Demand(bool value, string error) { if (!value) throw new InvalidOperationException(error); }
    static string Protected(string root) { return Path.Combine(root, "protected", "runtime-spine.db"); }
    static string Outside(string root) { return Path.Combine(root, "outside", "outside.txt"); }

    public static int Main(string[] args) {
        if (args.Length < 2) return 64;
        string mode = args[0], root = Path.GetFullPath(args[1]);
        if (!File.Exists(Path.Combine(root,"SPIKE_ONLY.marker"))) return 64;
        try {
            if (mode == "--attack") { Save(Path.Combine(root,"notes",args[4]+"-result.json"), Attack(root,args[2],int.Parse(args[3]))); return 0; }
            if (mode == "--child") { RunChild(root,args[2],int.Parse(args[3])); return 0; }
            if (mode == "--bootstrap") return Bootstrap(root);
            if (mode == "--run") return Run(root);
            return 64;
        } catch (Exception e) {
            // Child failures are not translated to PASS; the outer oracle requires their files.
            if (mode == "--run" || mode == "--bootstrap") {
                Directory.CreateDirectory(root);
                Save(Path.Combine(root,"result.json"),new { status="ENVIRONMENT_BLOCKED", phase=mode, error=e.GetType().Name, detail=e.Message, qualification="NOT_PROVEN" });
            }
            return 2;
        }
    }

    static int Bootstrap(string root) {
        Directory.CreateDirectory(root);
        var token = Token();
        Save(Path.Combine(root,"bootstrap-token.json"),token);
        if (!B(token,"elevated") && !B(token,"administrator_enabled")) return Run(root);
        // The bootstrap may be elevated on CI; no-admin proof comes only from --run below.
        // No policy/firewall/UAC settings are changed. If UAC supplies no limited token,
        // the fixture must report unsupported, rather than impersonate a no-admin result.
        IntPtr current = IntPtr.Zero, linkedInfo=IntPtr.Zero, linked=IntPtr.Zero;
        try {
            Check(OpenProcessToken(GetCurrentProcess(),0x0008,out current),"OpenProcessToken");
            linkedInfo=Info(current,19); linked=Marshal.ReadIntPtr(linkedInfo);
            var si=new STARTUPINFO(); si.cb=Marshal.SizeOf(typeof(STARTUPINFO));
            PROCESS_INFORMATION pi;
            Check(CreateProcessWithTokenW(linked,0,Exe,new StringBuilder(Q(Exe)+" --run "+Q(root)),0x08000000,IntPtr.Zero,root,ref si,out pi),"CreateProcessWithTokenW limited bootstrap");
            try { uint wait=WaitForSingleObject(pi.hProcess,90000); if(wait!=0){TerminateProcess(pi.hProcess,124); throw new TimeoutException("limited bootstrap did not finish");} uint exit; Check(GetExitCodeProcess(pi.hProcess,out exit),"GetExitCodeProcess"); return (int)exit; }
            finally { CloseHandle(pi.hThread);CloseHandle(pi.hProcess); }
        } finally { if(linked!=IntPtr.Zero)CloseHandle(linked); if(linkedInfo!=IntPtr.Zero)Marshal.FreeHGlobal(linkedInfo); if(current!=IntPtr.Zero)CloseHandle(current); }
    }

    static int Run(string root) {
        var parent=Token();
        Demand(!B(parent,"elevated") && !B(parent,"administrator_enabled"),"NO_ADMIN_PROOF_MISSING: probe must run from a non-elevated token with Administrators disabled");
        Demand(!B(parent,"appcontainer"),"Parent must be outside AppContainer to establish accessible negative controls");
        Demand(File.Exists(Path.Combine(root,"SPIKE_ONLY.marker")),"Fixture marker missing; arbitrary paths refused");
        foreach(string name in new[]{"notes","read","protected","outside"}) Directory.CreateDirectory(Path.Combine(root,name));
        string secret="R1-SENTINEL-"+Guid.NewGuid().ToString("N"), outer="OUTSIDE-SENTINEL-"+Guid.NewGuid().ToString("N");
        File.WriteAllText(Protected(root),secret); File.WriteAllText(Outside(root),outer);
        File.WriteAllText(Path.Combine(root,"read","diagnostic.txt"),"DIAGNOSTIC_FIXTURE");
        // All attempted mutation targets are disposable sentinels owned by this probe.
        string profile="aitest-spike-"+Guid.NewGuid().ToString("N"); IntPtr sid=IntPtr.Zero;
        var result=new Dictionary<string,object>{{"status","NOT_PROVEN"},{"probe","APPCONTAINER_ZERO_CAPABILITIES_V1"},{"parent_token",parent},{"profile",profile},{"os",Environment.OSVersion.VersionString},{"source_head","042a88a3fa3ac93cecb7b0d3ad5ff4b7f6bd71ac"}};
        try {
            int hr=CreateAppContainerProfile(profile,profile,"Disposable AITest isolation proof",IntPtr.Zero,0,out sid);
            if(hr<0)Marshal.ThrowExceptionForHR(hr);
            string sidText=new SecurityIdentifier(sid).Value; result["appcontainer_sid"]=sidText;
            ConfigureAcl(root,sidText,false,true,false);
            ConfigureAcl(Path.Combine(root,"bin"),sidText,false,false,true);
            ConfigureAcl(Path.Combine(root,"read"),sidText,false,false,true);
            ConfigureAcl(Path.Combine(root,"notes"),sidText,true,false,true);
            DenyContainer(Path.Combine(root,"protected"),sidText);
            DenyContainer(Path.Combine(root,"outside"),sidText);
            string fixtureMarker=Path.Combine(root,"SPIKE_ONLY.marker"); var markerAcl=File.GetAccessControl(fixtureMarker);
            markerAcl.AddAccessRule(new FileSystemAccessRule(new SecurityIdentifier(sidText),FileSystemRights.Read,AccessControlType.Allow));File.SetAccessControl(fixtureMarker,markerAcl);
            bool parentReadControl=File.ReadAllText(Protected(root))==secret && File.ReadAllText(Outside(root))==outer && File.ReadAllText(Path.Combine(root,"read","diagnostic.txt"))=="DIAGNOSTIC_FIXTURE";
            result["parent_read_controls"]=parentReadControl;Demand(parentReadControl,"PARENT_READ_CONTROL_FAILED");
            // Executable remains outside the writable notes root; grant only read/execute.
            // The wrapper placed it in root/bin before these protected ACLs were applied.
            Demand(Exe.StartsWith(Path.Combine(root,"bin")+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase),"Probe executable must be under the fixture bin directory");
            string junction=Path.Combine(root,"notes","escape");
            var junctionResult=Spawn(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),"cmd.exe"),"/d /c mklink /J "+Q(junction)+" "+Q(Path.Combine(root,"protected")),root,10000);
            result["junction_setup"]=junctionResult;
            Demand(Directory.Exists(junction),"JUNCTION_FIXTURE_UNAVAILABLE");
            using(var fixture=new TcpFixture()) {
                fixture.Control(); result["network_parent_control"]=true;
                result["launch"]=LaunchContainer(Exe,"--child "+Q(root)+" "+Q(sidText)+" "+fixture.Port,root,sid);
                var child=Read(Path.Combine(root,"notes","child-result.json"));
                var cmd=Read(Path.Combine(root,"notes","cmd-result.json"));
                var ps=Read(Path.Combine(root,"notes","powershell-result.json"));
                result["child"]=child; result["cmd_descendant"]=cmd; result["powershell_descendant"]=ps;
                bool intact=File.ReadAllText(Protected(root))==secret && File.ReadAllText(Outside(root))==outer && File.ReadAllText(Path.Combine(root,"read","diagnostic.txt"))=="DIAGNOSTIC_FIXTURE";
                result["sentinels_intact"]=intact;
                result["permitted_cmd_write"]=File.Exists(Path.Combine(root,"notes","cmd-note.txt"));
                result["permitted_powershell_write"]=File.ReadAllText(Path.Combine(root,"notes","powershell-note.txt"))=="PS_ALLOWED";
                bool attackOK=AttackPassed(D(child,"attack")) && AttackPassed(cmd) && AttackPassed(ps);
                // Access denied is affirmative OS evidence. Timeout/refusal/DNS failure is not.
                bool all=B(child,"permitted_write") && B(child,"permitted_read") && B(result,"permitted_cmd_write") && B(result,"permitted_powershell_write") && intact && attackOK;
                string[] markers=fixture.Markers(); result["network_connection_markers"]=markers;
                bool parentSeen=false, childSeen=false; foreach(string marker in markers){if(marker=="PARENT_CONTROL")parentSeen=true;else childSeen=true;}
                result["network_server_observed_control_only"]=parentSeen && !childSeen; all=all && parentSeen && !childSeen;
                result["status"]=all?"PASS_BOUNDED_NATIVE_FIXTURE":"FAIL";
                result["qualification"]=all?"L2_WINDOWS_PRIMITIVE_ONLY":"NOT_PROVEN";
                result["production_general_worker"]= "NOT_IMPLEMENTED_BY_THIS_SPIKE";
                result["bank_scope"]="NO_BANK_TARGETS_OR_CREDENTIALS";
            }
        } catch(Exception e) { result["status"]="ENVIRONMENT_BLOCKED_OR_INCOMPLETE";result["error"]=e.GetType().Name;result["detail"]=e.Message;result["qualification"]="NOT_PROVEN"; }
        finally { if(sid!=IntPtr.Zero)FreeSid(sid); int cleanup=DeleteAppContainerProfile(profile);result["profile_delete_hresult"]=cleanup;
            if(cleanup<0 && (string)result["status"]=="PASS_BOUNDED_NATIVE_FIXTURE"){result["status"]="PARTIAL_CLEANUP_REQUIRED";result["qualification"]="NOT_PROVEN";}
            Save(Path.Combine(root,"result.json"),result); }
        return (string)result["status"]=="PASS_BOUNDED_NATIVE_FIXTURE"?0:2;
    }

    static void ConfigureAcl(string path,string packageSid,bool write,bool protect,bool inherit) {
        var acl=Directory.GetAccessControl(path);
        if(protect) {
            acl.SetAccessRuleProtection(true,false);
            acl.AddAccessRule(new FileSystemAccessRule(WindowsIdentity.GetCurrent().User,FileSystemRights.FullControl,InheritanceFlags.ContainerInherit|InheritanceFlags.ObjectInherit,PropagationFlags.None,AccessControlType.Allow));
            acl.AddAccessRule(new FileSystemAccessRule(new SecurityIdentifier(WellKnownSidType.LocalSystemSid,null),FileSystemRights.FullControl,InheritanceFlags.ContainerInherit|InheritanceFlags.ObjectInherit,PropagationFlags.None,AccessControlType.Allow));
        }
        acl.AddAccessRule(new FileSystemAccessRule(new SecurityIdentifier(packageSid),write?FileSystemRights.Modify:FileSystemRights.ReadAndExecute,inherit?InheritanceFlags.ContainerInherit|InheritanceFlags.ObjectInherit:InheritanceFlags.None,PropagationFlags.None,AccessControlType.Allow));
        Directory.SetAccessControl(path,acl);
    }

    static void DenyContainer(string path,string packageSid) {
        var acl=Directory.GetAccessControl(path);
        acl.AddAccessRule(new FileSystemAccessRule(new SecurityIdentifier(packageSid),FileSystemRights.FullControl,InheritanceFlags.ContainerInherit|InheritanceFlags.ObjectInherit,PropagationFlags.None,AccessControlType.Deny));
        Directory.SetAccessControl(path,acl);
    }

    static void RunChild(string root,string sid,int port) {
        var result=new Dictionary<string,object>();
        File.WriteAllText(Path.Combine(root,"notes","note.txt"),"NOTE_ALLOWED");
        result["permitted_write"]=File.ReadAllText(Path.Combine(root,"notes","note.txt"))=="NOTE_ALLOWED";
        result["permitted_read"]=File.ReadAllText(Path.Combine(root,"read","diagnostic.txt"))=="DIAGNOSTIC_FIXTURE";
        result["attack"]=Attack(root,sid,port);
        string childArgs=" --attack "+Q(root)+" "+Q(sid)+" "+port;
        string command="@echo off\r\necho CMD_ALLOWED>"+Q(Path.Combine(root,"notes","cmd-note.txt"))+"\r\n"+Q(Exe)+childArgs+" cmd\r\necho CMD_ATTACK>"+Q(Protected(root))+"\r\necho CMD_ATTACK>"+Q(Outside(root))+"\r\necho CMD_ATTACK>"+Q(Path.Combine(root,"read","diagnostic.txt"))+"\r\n";
        string commandPath=Path.Combine(root,"notes","shell-proof.cmd"); File.WriteAllText(commandPath,command,Encoding.Default);
        result["cmd_process"]=Spawn(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),"cmd.exe"),"/d /s /c \"\""+commandPath+"\"\"",root,15000);
        string ps="[IO.File]::WriteAllText("+PSQ(Path.Combine(root,"notes","powershell-note.txt"))+",'PS_ALLOWED'); & "+PSQ(Exe)+" --attack "+PSQ(root)+" "+PSQ(sid)+" "+port+" powershell; try {[IO.File]::WriteAllText("+PSQ(Protected(root))+",'PS_ATTACK')} catch {}; try {[IO.File]::WriteAllText("+PSQ(Outside(root))+",'PS_ATTACK')} catch {}; try {[IO.File]::WriteAllText("+PSQ(Path.Combine(root,"read","diagnostic.txt"))+",'PS_ATTACK')} catch {}";
        result["powershell_process"]=Spawn(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),"WindowsPowerShell","v1.0","powershell.exe"),"-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand "+Convert.ToBase64String(Encoding.Unicode.GetBytes(ps)),root,25000);
        Save(Path.Combine(root,"notes","child-result.json"),result);
    }

    static Dictionary<string,object> Attack(string root,string sid,int port) {
        var token=Token(); var result=new Dictionary<string,object>{{"token",token}};
        result["correct_appcontainer_sid"]=B(token,"appcontainer") && (string)token["appcontainer_sid"]==sid && Convert.ToInt32(token["capability_count"])==0;
        result["protected"]=WriteAttack(Protected(root)); result["outside"]=WriteAttack(Outside(root));
        result["protected_read"]=ReadAttack(Protected(root));result["outside_read"]=ReadAttack(Outside(root));
        result["readonly_write"]=WriteAttack(Path.Combine(root,"read","diagnostic.txt"));
        result["traversal"]=WriteAttack(Path.Combine(root,"notes","..","protected","runtime-spine.db"));
        result["case"]=WriteAttack(Outside(root).ToUpperInvariant());
        result["junction"]=WriteAttack(Path.Combine(root,"notes","escape","runtime-spine.db"));
        result["network"]=Network(port);
        return result;
    }
    static Dictionary<string,object> ReadAttack(string path) {
        try { File.ReadAllText(path);return new Dictionary<string,object>{{"read",true},{"denied",false}}; }
        catch(UnauthorizedAccessException e){return new Dictionary<string,object>{{"read",false},{"denied",true},{"error",e.GetType().Name},{"hresult",e.HResult}};}
        catch(Exception e){return new Dictionary<string,object>{{"read",false},{"denied",false},{"error",e.GetType().Name},{"hresult",e.HResult}};}
    }
    static Dictionary<string,object> WriteAttack(string path) {
        try { File.WriteAllText(path,"UNAUTHORIZED_MUTATION"); return new Dictionary<string,object>{{"wrote",true},{"denied",false}}; }
        catch(UnauthorizedAccessException e) { return new Dictionary<string,object>{{"wrote",false},{"denied",true},{"error",e.GetType().Name},{"hresult",e.HResult}}; }
        catch(Exception e) { return new Dictionary<string,object>{{"wrote",false},{"denied",false},{"error",e.GetType().Name},{"hresult",e.HResult}}; }
    }
    static Dictionary<string,object> Network(int port) {
        try { using(var s=new Socket(AddressFamily.InterNetwork,SocketType.Stream,ProtocolType.Tcp)) { var ar=s.BeginConnect(IPAddress.Loopback,port,null,null); if(!ar.AsyncWaitHandle.WaitOne(3000))return new Dictionary<string,object>{{"denied",false},{"error","TIMEOUT_INSUFFICIENT_EVIDENCE"}}; s.EndConnect(ar);s.Send(Encoding.ASCII.GetBytes("CHILD_UNAUTHORIZED")); return new Dictionary<string,object>{{"denied",false},{"connected",true}}; } }
        catch(SocketException e) { return new Dictionary<string,object>{{"denied",e.NativeErrorCode==10013},{"connected",false},{"error",e.SocketErrorCode.ToString()},{"native_error",e.NativeErrorCode}}; }
        catch(Exception e) { return new Dictionary<string,object>{{"denied",false},{"error",e.GetType().Name}}; }
    }
    static bool AttackPassed(Dictionary<string,object> a) {
        if(!B(a,"correct_appcontainer_sid"))return false;
        foreach(string k in new[]{"protected","outside","protected_read","outside_read","readonly_write","traversal","case","junction","network"})if(!B(D(a,k),"denied"))return false;
        return true;
    }
    static Dictionary<string,object> Spawn(string executable,string arguments,string cwd,int timeout) {
        try { using(var p=Process.Start(new ProcessStartInfo(executable,arguments){UseShellExecute=false,CreateNoWindow=true,WorkingDirectory=cwd})) { if(!p.WaitForExit(timeout)){p.Kill();return new Dictionary<string,object>{{"started",true},{"timeout",true}};}return new Dictionary<string,object>{{"started",true},{"exit",p.ExitCode}};} }
        catch(Exception e){return new Dictionary<string,object>{{"started",false},{"error",e.GetType().Name},{"detail",e.Message}};}
    }

    sealed class TcpFixture:IDisposable {
        readonly TcpListener listener=new TcpListener(IPAddress.Loopback,0); readonly List<string> markers=new List<string>(); readonly Thread thread;
        public int Port {get;private set;}
        public TcpFixture(){listener.Start();Port=((IPEndPoint)listener.LocalEndpoint).Port;thread=new Thread(Serve);thread.IsBackground=true;thread.Start();}
        void Serve(){try {while(true){using(var c=listener.AcceptTcpClient()){c.ReceiveTimeout=5000;byte[] b=new byte[128];int n=c.GetStream().Read(b,0,b.Length);lock(markers)markers.Add(Encoding.ASCII.GetString(b,0,n));}}}catch(SocketException){}catch(ObjectDisposedException){}catch(IOException){} }
        public void Control(){using(var c=new TcpClient()){c.Connect(IPAddress.Loopback,Port);byte[] b=Encoding.ASCII.GetBytes("PARENT_CONTROL");c.GetStream().Write(b,0,b.Length);} }
        public string[] Markers(){lock(markers)return markers.ToArray();}
        public void Dispose(){listener.Stop();thread.Join(2000);}
    }

    static Dictionary<string,object> Token() {
        IntPtr t;Check(OpenProcessToken(GetCurrentProcess(),8,out t),"OpenProcessToken");
        try { var d=new Dictionary<string,object>{{"elevated",IntInfo(t,20)!=0},{"administrator_enabled",new WindowsPrincipal(WindowsIdentity.GetCurrent()).IsInRole(WindowsBuiltInRole.Administrator)},{"appcontainer",IntInfo(t,29)!=0}};
            if(B(d,"appcontainer")){IntPtr info=Info(t,31);try{d["appcontainer_sid"]=new SecurityIdentifier(Marshal.ReadIntPtr(info)).Value;}finally{Marshal.FreeHGlobal(info);}d["capability_count"]=IntInfo(t,30);}else{d["appcontainer_sid"]="";d["capability_count"]=-1;}
            return d;
        }finally{CloseHandle(t);}
    }
    static int IntInfo(IntPtr token,int type){IntPtr p=Info(token,type);try{return Marshal.ReadInt32(p);}finally{Marshal.FreeHGlobal(p);}}
    static IntPtr Info(IntPtr token,int type){int n;GetTokenInformation(token,type,IntPtr.Zero,0,out n);if(n<=0)throw new Win32Exception(Marshal.GetLastWin32Error(),"GetTokenInformation size "+type);IntPtr p=Marshal.AllocHGlobal(n);if(!GetTokenInformation(token,type,p,n,out n)){int error=Marshal.GetLastWin32Error();Marshal.FreeHGlobal(p);throw new Win32Exception(error,"GetTokenInformation "+type);}return p;}
    static void Check(bool ok,string name){if(!ok)throw new Win32Exception(Marshal.GetLastWin32Error(),name);}

    static object LaunchContainer(string exe,string args,string cwd,IntPtr sid) {
        IntPtr attr=IntPtr.Zero,cap=IntPtr.Zero,environment=IntPtr.Zero,job=IntPtr.Zero;PROCESS_INFORMATION pi=new PROCESS_INFORMATION(); bool launched=false;
        try {
            IntPtr size=IntPtr.Zero;InitializeProcThreadAttributeList(IntPtr.Zero,1,0,ref size);attr=Marshal.AllocHGlobal(size);Check(InitializeProcThreadAttributeList(attr,1,0,ref size),"InitializeProcThreadAttributeList");
            var sc=new SECURITY_CAPABILITIES{AppContainerSid=sid,Capabilities=IntPtr.Zero,CapabilityCount=0,Reserved=0};cap=Marshal.AllocHGlobal(Marshal.SizeOf(sc));Marshal.StructureToPtr(sc,cap,false);
            Check(UpdateProcThreadAttribute(attr,0,(IntPtr)0x00020009,cap,(IntPtr)Marshal.SizeOf(sc),IntPtr.Zero,IntPtr.Zero),"UpdateProcThreadAttribute SECURITY_CAPABILITIES");
            var si=new STARTUPINFOEX();si.StartupInfo.cb=Marshal.SizeOf(si);si.lpAttributeList=attr;
            string system=Environment.GetFolderPath(Environment.SpecialFolder.System),windows=Directory.GetParent(system).FullName;
            Directory.CreateDirectory(Path.Combine(cwd,"notes","temp"));
            var env=new SortedDictionary<string,string>(StringComparer.OrdinalIgnoreCase){{"SystemRoot",windows},{"WINDIR",windows},{"COMSPEC",Path.Combine(system,"cmd.exe")},{"PATH",system},{"TEMP",Path.Combine(cwd,"notes","temp")},{"TMP",Path.Combine(cwd,"notes","temp")}};
            var block=new StringBuilder();foreach(var pair in env)block.Append(pair.Key).Append('=').Append(pair.Value).Append('\0');block.Append('\0');environment=Marshal.StringToHGlobalUni(block.ToString());
            job=CreateJobObject(IntPtr.Zero,null);Check(job!=IntPtr.Zero,"CreateJobObject");
            var limit=new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();limit.BasicLimitInformation.LimitFlags=0x00002000; // KILL_ON_JOB_CLOSE: cleanup only, not security proof.
            Check(SetInformationJobObject(job,9,ref limit,Marshal.SizeOf(limit)),"SetInformationJobObject");
            Check(CreateProcessW(exe,new StringBuilder(Q(exe)+" "+args),IntPtr.Zero,IntPtr.Zero,false,0x00080000|0x00000400|0x08000000|0x00000004,environment,cwd,ref si,out pi),"CreateProcessW AppContainer");launched=true;
            Check(AssignProcessToJobObject(job,pi.hProcess),"AssignProcessToJobObject");
            if(ResumeThread(pi.hThread)==0xffffffff)throw new Win32Exception(Marshal.GetLastWin32Error(),"ResumeThread");
            uint wait=WaitForSingleObject(pi.hProcess,65000);if(wait!=0)throw new TimeoutException("AppContainer child timeout");uint exit;Check(GetExitCodeProcess(pi.hProcess,out exit),"GetExitCodeProcess");return new {started=true,exit_code=exit,capabilities=0,inherited_handles=false,environment="SANITIZED",timeout_ms=65000};
        } finally {
            if(launched){if(WaitForSingleObject(pi.hProcess,0)!=0)TerminateProcess(pi.hProcess,124);CloseHandle(pi.hThread);CloseHandle(pi.hProcess);}if(job!=IntPtr.Zero)CloseHandle(job);
            if(attr!=IntPtr.Zero){DeleteProcThreadAttributeList(attr);Marshal.FreeHGlobal(attr);}if(cap!=IntPtr.Zero)Marshal.FreeHGlobal(cap);if(environment!=IntPtr.Zero)Marshal.FreeHGlobal(environment);
        }
    }

    [StructLayout(LayoutKind.Sequential)]struct SECURITY_CAPABILITIES{public IntPtr AppContainerSid,Capabilities;public uint CapabilityCount,Reserved;}
    [StructLayout(LayoutKind.Sequential,CharSet=CharSet.Unicode)]struct STARTUPINFO{public int cb;public string lpReserved,lpDesktop,lpTitle;public uint dwX,dwY,dwXSize,dwYSize,dwXCountChars,dwYCountChars,dwFillAttribute,dwFlags;public short wShowWindow,cbReserved2;public IntPtr lpReserved2,hStdInput,hStdOutput,hStdError;}
    [StructLayout(LayoutKind.Sequential)]struct STARTUPINFOEX{public STARTUPINFO StartupInfo;public IntPtr lpAttributeList;}
    [StructLayout(LayoutKind.Sequential)]struct PROCESS_INFORMATION{public IntPtr hProcess,hThread;public uint dwProcessId,dwThreadId;}
    [StructLayout(LayoutKind.Sequential)]struct JOBOBJECT_BASIC_LIMIT_INFORMATION{public long PerProcessUserTimeLimit,PerJobUserTimeLimit;public uint LimitFlags;public UIntPtr MinimumWorkingSetSize,MaximumWorkingSetSize;public uint ActiveProcessLimit;public UIntPtr Affinity;public uint PriorityClass,SchedulingClass;}
    [StructLayout(LayoutKind.Sequential)]struct IO_COUNTERS{public ulong ReadOperationCount,WriteOperationCount,OtherOperationCount,ReadTransferCount,WriteTransferCount,OtherTransferCount;}
    [StructLayout(LayoutKind.Sequential)]struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION{public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;public IO_COUNTERS IoInfo;public UIntPtr ProcessMemoryLimit,JobMemoryLimit,PeakProcessMemoryUsed,PeakJobMemoryUsed;}
    [DllImport("userenv.dll",CharSet=CharSet.Unicode)]static extern int CreateAppContainerProfile(string name,string display,string description,IntPtr capabilities,uint count,out IntPtr sid);
    [DllImport("userenv.dll",CharSet=CharSet.Unicode)]static extern int DeleteAppContainerProfile(string name);
    [DllImport("advapi32.dll",SetLastError=true)]static extern bool OpenProcessToken(IntPtr process,uint desired,out IntPtr token);
    [DllImport("advapi32.dll",SetLastError=true)]static extern bool GetTokenInformation(IntPtr token,int type,IntPtr info,int length,out int needed);
    [DllImport("advapi32.dll")]static extern IntPtr FreeSid(IntPtr sid);
    [DllImport("kernel32.dll")]static extern IntPtr GetCurrentProcess();
    [DllImport("kernel32.dll",SetLastError=true)]static extern bool CloseHandle(IntPtr handle);
    [DllImport("kernel32.dll",SetLastError=true)]static extern bool InitializeProcThreadAttributeList(IntPtr list,int count,int flags,ref IntPtr size);
    [DllImport("kernel32.dll",SetLastError=true)]static extern bool UpdateProcThreadAttribute(IntPtr list,uint flags,IntPtr attribute,IntPtr value,IntPtr size,IntPtr previous,IntPtr returned);
    [DllImport("kernel32.dll")]static extern void DeleteProcThreadAttributeList(IntPtr list);
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)]static extern bool CreateProcessW(string app,StringBuilder command,IntPtr processAttributes,IntPtr threadAttributes,bool inherit,uint flags,IntPtr environment,string cwd,ref STARTUPINFOEX startup,out PROCESS_INFORMATION process);
    [DllImport("advapi32.dll",CharSet=CharSet.Unicode,SetLastError=true)]static extern bool CreateProcessWithTokenW(IntPtr token,uint logonFlags,string app,StringBuilder command,uint flags,IntPtr environment,string cwd,ref STARTUPINFO startup,out PROCESS_INFORMATION process);
    [DllImport("kernel32.dll",SetLastError=true)]static extern uint WaitForSingleObject(IntPtr handle,uint milliseconds);
    [DllImport("kernel32.dll",SetLastError=true)]static extern bool GetExitCodeProcess(IntPtr process,out uint exit);
    [DllImport("kernel32.dll",SetLastError=true)]static extern bool TerminateProcess(IntPtr process,uint exit);
    [DllImport("kernel32.dll",SetLastError=true)]static extern uint ResumeThread(IntPtr thread);
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)]static extern IntPtr CreateJobObject(IntPtr attributes,string name);
    [DllImport("kernel32.dll",SetLastError=true)]static extern bool SetInformationJobObject(IntPtr job,int information,ref JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits,int size);
    [DllImport("kernel32.dll",SetLastError=true)]static extern bool AssignProcessToJobObject(IntPtr job,IntPtr process);
}
