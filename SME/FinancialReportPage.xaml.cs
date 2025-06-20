using Microsoft.Maui.Controls;
using SkiaSharp.Views.Maui;
using SkiaSharp;
using SkiaSharp.Views.Maui.Controls;
using System;

namespace SME
{
    public partial class FinancialReportPage : ContentPage
    {
        public FinancialReportPage()
        {
            InitializeComponent();

            var canvasView = new SKCanvasView
            {
                HeightRequest = 180,
                WidthRequest = 400
            };
            canvasView.PaintSurface += OnCanvasViewPaintSurface;
            BarChartPlaceholder.Content = canvasView;

            UpdateKeyMetrics();
        }

        private void OnStartDateClicked(object sender, EventArgs e)
        {
            StartDatePicker.Focus();
        }

        private void OnEndDateClicked(object sender, EventArgs e)
        {
            EndDatePicker.Focus();
        }

        private void StartDatePicker_DateSelected(object sender, DateChangedEventArgs e)
        {
            StartDateButton.Text = $"?? {e.NewDate:yyyy-MM-dd}";
        }

        private void EndDatePicker_DateSelected(object sender, DateChangedEventArgs e)
        {
            EndDateButton.Text = $"?? {e.NewDate:yyyy-MM-dd}";
        }

        private async void OnGeneratePdfClicked(object sender, EventArgs e)
        {
            await DisplayAlert("PDF", "PDF Generated Successfully!", "OK");
        }

        private string CalculatePercentageChange(float thisPeriod, float endPeriod)
        {
            if (endPeriod == 0)
                return "N/A";
            float percentageChange = ((thisPeriod - endPeriod) / endPeriod) * 100;
            return $"{percentageChange:0}%";
        }

        private void UpdateKeyMetrics()
        {
            float revenueThis = 150000f, revenueEnd = 440000f;
            float netProfitThis = 21000f, netProfitEnd = 24000f;
            float expensesThis = 12000f, expensesEnd = 10000f;
            float costGoodsThis = 50000f, costGoodsEnd = 45000f;
            float cashThis = 20000f, cashEnd = 18000f;

            RevenueThisPeriodLabel.Text = $"?{revenueThis:0,0}";
            RevenueEndPeriodLabel.Text = $"?{revenueEnd:0,0}";
            RevenuePercentChangeLabel.Text = CalculatePercentageChange(revenueThis, revenueEnd);

            NetProfitThisPeriodLabel.Text = $"?{netProfitThis:0,0}";
            NetProfitEndPeriodLabel.Text = $"?{netProfitEnd:0,0}";
            NetProfitPercentChangeLabel.Text = CalculatePercentageChange(netProfitThis, netProfitEnd);

            ExpensesThisPeriodLabel.Text = $"?{expensesThis:0,0}";
            ExpensesEndPeriodLabel.Text = $"?{expensesEnd:0,0}";
            ExpensesPercentChangeLabel.Text = CalculatePercentageChange(expensesThis, expensesEnd);

            CostOfGoodsThisPeriodLabel.Text = $"?{costGoodsThis:0,0}";
            CostOfGoodsEndPeriodLabel.Text = $"?{costGoodsEnd:0,0}";
            CostOfGoodsPercentChangeLabel.Text = CalculatePercentageChange(costGoodsThis, costGoodsEnd);

            CashOnHandThisPeriodLabel.Text = $"?{cashThis:0,0}";
            CashOnHandEndPeriodLabel.Text = $"?{cashEnd:0,0}";
            CashOnHandPercentChangeLabel.Text = CalculatePercentageChange(cashThis, cashEnd);
        }

        private void OnCanvasViewPaintSurface(object sender, SKPaintSurfaceEventArgs e)
        {
            var surface = e.Surface;
            var canvas = surface.Canvas;
            canvas.Clear(SKColors.White);

            float[] values = { 150000f, 21000f, 12000f, 50000f, 20000f };
            string[] labels = { "Revenue", "Profit", "Expenses", "COGS", "Cash" };

            float maxValue = 150000f;
            float barWidth = 50;
            float spacing = 30;
            float x = 30;
            float chartHeight = e.Info.Height - 40;

            var barPaint = new SKPaint
            {
                Color = SKColors.Indigo,
                IsAntialias = true
            };

            var labelPaint = new SKPaint
            {
                TextSize = 20,
                Color = SKColors.Black
            };

            for (int i = 0; i < values.Length; i++)
            {
                float barHeight = (values[i] / maxValue) * chartHeight;
                float y = e.Info.Height - barHeight - 20;
                canvas.DrawRect(x, y, barWidth, barHeight, barPaint);
                canvas.DrawText(labels[i], x, e.Info.Height - 5, labelPaint);
                x += barWidth + spacing;
            }
        }
    }
}
