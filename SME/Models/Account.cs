namespace SME.Models
{
    public class Account
    {
        public string FirstName { get; set; }
        public string MiddleName { get; set; }
        public string LastName { get; set; }
        public string PhoneNumber { get; set; }
        public string Pin { get; set; }

        public string GetFullName()
        {
            return $"{FirstName} {MiddleName} {LastName}";
        }
    }

}
