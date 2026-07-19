using System;
using System.Diagnostics;
using System.Threading;
using System.Windows.Forms;

namespace BillingClientApp
{
    static class Program
    {
        [STAThread]
        static void Main()
        {
            // Ensure only one instance
            using (var mutex = new Mutex(true, "RRBillingClientApp_Mutex", out bool createdNew))
            {
                if (!createdNew)
                {
                    // Another instance is already running — poke it
                    Debug.WriteLine("[ClientApp] Already running, exiting.");
                    return;
                }

                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);

                try
                {
                    Application.Run(new ClientAppForm());
                }
                catch (Exception ex)
                {
                    Debug.WriteLine($"[ClientApp] Fatal error: {ex.Message}");
                }
            }
        }
    }
}
