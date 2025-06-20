using Microsoft.Maui.Controls;
using Microsoft.Maui.Storage;


namespace SME
{
    public partial class HomePage : ContentPage
    {
        public HomePage()
        {
            InitializeComponent();
        }

        private async void OnRecordSalesTapped(object sender, EventArgs e)
        {

            await Navigation.PushAsync(new RecordSalesPage());
        }

        private async void OnStockInTapped(object sender, EventArgs e)
        {
            
            await Navigation.PushAsync(new StockInPage());
        }

        private async void OnManageInventoryTapped(object sender, EventArgs e)
        {
            await Navigation.PushAsync(new ManageInventoryPage());
        }

        private async void OnExpensesTapped(object sender, EventArgs e)
        {
            await Navigation.PushAsync(new RecordExpensesPage());
        }

        private async void OnDebtorsCardTapped(object sender, EventArgs e)
        {
            await Navigation.PushAsync(new DebtorsPage());
        }

        private async void OnFinancialReportTapped(object sender, EventArgs e)
        {
            await Navigation.PushAsync(new FinancialReportPage());
        }

        private async void OnSettingsTapped(object sender, EventArgs e)
        {
            await Navigation.PushAsync(new SettingsPage());
        }
    }



}
