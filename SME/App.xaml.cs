namespace SME
{
    public partial class App : Application
    {
        // ✅ Global phone number accessible throughout the app
        public static string CurrentPhoneNumber { get; set; } = "0000000000"; // Default placeholder

        public App()
        {
            InitializeComponent();
            MainPage = new AppShell(); // ✅ Use Shell-based navigation
        }
    }
}
