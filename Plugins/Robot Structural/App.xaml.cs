using System.Windows;

namespace GithubConnect
{
    public partial class App : Application
    {
        private void Application_Startup(object sender, StartupEventArgs e)
        {
            PluginEntry.Run();
        }
    }
}