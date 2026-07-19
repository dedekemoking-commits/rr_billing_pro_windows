using System;
using System.Collections;
using System.ComponentModel;
using System.Configuration.Install;
using System.Diagnostics;
using System.Linq;
using System.Reflection;
using System.ServiceProcess;
using System.Threading;

namespace BillingClientService
{
    static class Program
    {
        static void Main(string[] args)
        {
            if (args.Length > 0)
            {
                string action = args[0].ToLowerInvariant();

                switch (action)
                {
                    case "--install":
                    case "/install":
                    case "-i":
                        InstallService();
                        break;

                    case "--uninstall":
                    case "/uninstall":
                    case "-u":
                        UninstallService();
                        break;

                    case "--console":
                    case "-c":
                        RunConsole();
                        break;

                    case "--help":
                    case "-h":
                    case "/?":
                        ShowHelp();
                        break;

                    default:
                        Console.WriteLine($"Unknown argument: {args[0]}");
                        ShowHelp();
                        break;
                }
                return;
            }

            ServiceBase[] ServicesToRun;
            ServicesToRun = new ServiceBase[]
            {
                new ServiceCore()
            };
            ServiceBase.Run(ServicesToRun);
        }

        static void InstallService()
        {
            try
            {
                ManagedInstallerClass.InstallHelper(new[] { Assembly.GetExecutingAssembly().Location });
                Console.WriteLine("Service installed successfully.");
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Install failed: {ex.Message}");
            }
        }

        static void UninstallService()
        {
            try
            {
                ManagedInstallerClass.InstallHelper(new[] { "/u", Assembly.GetExecutingAssembly().Location });
                Console.WriteLine("Service uninstalled successfully.");
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Uninstall failed: {ex.Message}");
            }
        }

        static void RunConsole()
        {
            Console.WriteLine("BillingClientService running in console mode...");
            Console.WriteLine("Press Ctrl+C to stop.\n");

            using (var service = new ServiceCore())
            {
                service.StartForConsole();

                var exitEvent = new ManualResetEvent(false);
                Console.CancelKeyPress += (sender, e) =>
                {
                    e.Cancel = true;
                    exitEvent.Set();
                };
                exitEvent.WaitOne();

                service.StopForConsole();
            }

            Console.WriteLine("Service stopped.");
        }

        static void ShowHelp()
        {
            Console.WriteLine("Usage:");
            Console.WriteLine("  BillingClientService              Run as Windows Service (default)");
            Console.WriteLine("  BillingClientService -c           Run in console mode (for debugging)");
            Console.WriteLine("  BillingClientService -i           Install as Windows Service");
            Console.WriteLine("  BillingClientService -u           Uninstall Windows Service");
        }
    }

    [RunInstaller(true)]
    public class ProjectInstaller : Installer
    {
        public ProjectInstaller()
        {
            var serviceProcessInstaller = new ServiceProcessInstaller
            {
                Account = ServiceAccount.LocalSystem
            };

            var serviceInstaller = new ServiceInstaller
            {
                ServiceName = "RRBillingClientService",
                DisplayName = "RR Billing Pro - Client Service",
                Description = "Warnet client service for RR Billing Pro. Manages TCP connection, " +
                              "heartbeat, and lock screen.",
                StartType = ServiceStartMode.Automatic,
                DelayedAutoStart = true,
            };

            Installers.Add(serviceProcessInstaller);
            Installers.Add(serviceInstaller);
        }
    }
}
