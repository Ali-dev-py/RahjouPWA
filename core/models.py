from django.db import models


class Tblcustomer(models.Model):
    customerid = models.IntegerField(db_column='CustomerID')
    custno = models.CharField(db_column='CustNo', max_length=20, db_collation='Arabic_CI_AS')
    custname = models.CharField(db_column='CustName', max_length=100, db_collation='Arabic_CI_AS')
    address = models.CharField(db_column='Address', max_length=250, db_collation='Arabic_CI_AS', blank=True, null=True)
    phone = models.CharField(db_column='Phone', max_length=100, db_collation='Arabic_CI_AS', blank=True, null=True)
    mobile = models.CharField(db_column='Mobile', max_length=100, db_collation='Arabic_CI_AS', blank=True, null=True)
    faxno = models.CharField(db_column='FaxNo', max_length=50, db_collation='Arabic_CI_AS', blank=True, null=True)
    status = models.CharField(db_column='Status', max_length=1, db_collation='Arabic_CI_AS')
    salestatus = models.SmallIntegerField(db_column='SaleStatus')
    eshterakno = models.CharField(db_column='EshterakNo', max_length=50, db_collation='Arabic_CI_AS', blank=True, null=True)
    credit = models.DecimalField(db_column='Credit', max_digits=18, decimal_places=0)
    companyname = models.CharField(db_column='CompanyName', max_length=50, db_collation='Arabic_CI_AS', blank=True, null=True)
    economno = models.CharField(db_column='EconomNo', max_length=50, db_collation='Arabic_CI_AS', blank=True, null=True)
    registno = models.CharField(db_column='RegistNo', max_length=50, db_collation='Arabic_CI_AS', blank=True, null=True)
    postcode = models.CharField(db_column='PostCode', max_length=50, db_collation='Arabic_CI_AS', blank=True, null=True)
    email = models.CharField(db_column='Email', max_length=50, db_collation='Arabic_CI_AS', blank=True, null=True)
    website = models.CharField(db_column='WebSite', max_length=50, db_collation='Arabic_CI_AS', blank=True, null=True)
    custdesc = models.CharField(db_column='CustDesc', max_length=500, db_collation='Arabic_CI_AS', blank=True, null=True)
    citytelcode = models.CharField(db_column='CityTelCode', max_length=10, db_collation='Arabic_CI_AS', blank=True, null=True)
    creditchkd = models.DecimalField(db_column='CreditChkd', max_digits=18, decimal_places=0, blank=True, null=True)
    semat = models.CharField(db_column='Semat', max_length=50, db_collation='Arabic_CI_AS', blank=True, null=True)
    usercount = models.IntegerField(db_column='UserCount', blank=True, null=True)
    callstatus = models.SmallIntegerField(db_column='CallStatus', blank=True, null=True)
    ranking = models.SmallIntegerField(db_column='Ranking', blank=True, null=True)
    callwithemailsend = models.BooleanField(db_column='CallWithEmailSend', blank=True, null=True)
    callwithtel = models.BooleanField(db_column='CallWithTel', blank=True, null=True)
    callwithfax = models.BooleanField(db_column='CallWithFax', blank=True, null=True)
    callwithletter = models.BooleanField(db_column='CallWithLetter', blank=True, null=True)
    custtypecode = models.SmallIntegerField(db_column='CustTypeCode', blank=True, null=True)
    createdby = models.CharField(db_column='CreatedBy', max_length=100, db_collation='Arabic_CI_AS', blank=True, null=True)
    createddate = models.CharField(db_column='CreatedDate', max_length=10, db_collation='Arabic_CI_AS', blank=True, null=True)
    lastupdatedby = models.CharField(db_column='LastUpdatedBy', max_length=100, db_collation='Arabic_CI_AS', blank=True, null=True)
    lastupdateddate = models.CharField(db_column='LastUpdatedDate', max_length=10, db_collation='Arabic_CI_AS', blank=True, null=True)
    uid = models.CharField(db_column='uID', max_length=10, db_collation='Arabic_CI_AS', blank=True, null=True)
    gcampainid = models.CharField(db_column='GCampainID', max_length=36, blank=True, null=True)
    gknowmodeid = models.CharField(db_column='GKnowModeID', max_length=36, blank=True, null=True)
    gcrmindustryid = models.CharField(db_column='GCrmIndustryID', max_length=36, blank=True, null=True)
    gprovinceid = models.CharField(db_column='GProvinceID', max_length=36, blank=True, null=True)
    gcityid = models.CharField(db_column='GCityID', max_length=36, blank=True, null=True)
    gsubdetailid = models.CharField(db_column='GSubDetailID', max_length=36, blank=True, null=True)
    gcustomerid = models.CharField(db_column='GCustomerID', primary_key=True, max_length=36)
    gcompanyid = models.CharField(db_column='GCompanyID', max_length=36, blank=True, null=True)
    nationalid = models.CharField(db_column='NationalID', max_length=50, db_collation='Arabic_CI_AS', blank=True, null=True)
    geshteraktypeid = models.CharField(db_column='GEshterakTypeID', max_length=36, blank=True, null=True)
    prename = models.CharField(db_column='PreName', max_length=50, db_collation='Arabic_CI_AS', blank=True, null=True)
    grouteid = models.CharField(db_column='GRouteID', max_length=36, blank=True, null=True)
    gareageoghrafiid = models.CharField(db_column='GAreaGeoghrafiID', max_length=36, blank=True, null=True)
    birthdate = models.CharField(db_column='BirthDate', max_length=10, db_collation='Arabic_CI_AS', blank=True, null=True)
    sentstatuscode = models.IntegerField(db_column='SentStatusCode', blank=True, null=True)
    registerdate = models.DateTimeField(db_column='RegisterDate')
    visitpriod = models.IntegerField(db_column='VisitPriod')
    cardno = models.CharField(db_column='CardNo', max_length=50, db_collation='Arabic_CI_AS', blank=True, null=True)
    customertypecode = models.SmallIntegerField(db_column='CustomerTypeCode')
    customertaxtype = models.SmallIntegerField(db_column='CustomerTaxType')
    debit = models.DecimalField(db_column='Debit', max_digits=18, decimal_places=0)
    deletedby = models.CharField(db_column='DeletedBy', max_length=36, blank=True, null=True)
    deleteddate = models.CharField(db_column='DeletedDate', max_length=10, db_collation='Arabic_CI_AS', blank=True, null=True)
    customername = models.CharField(db_column='CustomerName', max_length=200, db_collation='Arabic_CI_AS', blank=True, null=True)
    mobile2 = models.CharField(db_column='Mobile2', max_length=100, db_collation='Arabic_CI_AS', blank=True, null=True)
    mobile3 = models.CharField(db_column='Mobile3', max_length=100, db_collation='Arabic_CI_AS', blank=True, null=True)
    mobile4 = models.CharField(db_column='Mobile4', max_length=100, db_collation='Arabic_CI_AS', blank=True, null=True)
    phone2 = models.CharField(db_column='Phone2', max_length=100, db_collation='Arabic_CI_AS', blank=True, null=True)
    phone3 = models.CharField(db_column='Phone3', max_length=100, db_collation='Arabic_CI_AS', blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'tblCustomer'


class Tblsanadrad(models.Model):
    sanadradid = models.IntegerField(db_column='SanadradID')
    debit = models.DecimalField(db_column='Debit', max_digits=18, decimal_places=0)
    credit = models.DecimalField(db_column='Credit', max_digits=18, decimal_places=0)
    acckind = models.SmallIntegerField(db_column='AccKind')
    serialid = models.IntegerField(db_column='SerialId', blank=True, null=True)
    description = models.CharField(db_column='Description', max_length=1000, db_collation='Arabic_CI_AS', blank=True, null=True)
    currencyprice = models.DecimalField(db_column='CurrencyPrice', max_digits=26, decimal_places=8, blank=True, null=True)
    currencyrate = models.DecimalField(db_column='CurrencyRate', max_digits=19, decimal_places=4)
    gsanadradid = models.CharField(db_column='GSanadradID', primary_key=True, max_length=36)
    gcompanyid = models.CharField(db_column='GCompanyID', max_length=36, blank=True, null=True)
    ggsanadradid = models.CharField(db_column='GGSanadradID', max_length=36)
    gaccid = models.CharField(db_column='GAccID', max_length=36, blank=True, null=True)
    gsanadid = models.ForeignKey('Tblsanad', models.DO_NOTHING, db_column='GSanadID', blank=True, null=True)
    gsubdetailid = models.CharField(db_column='GSubDetailID', max_length=36, blank=True, null=True)
    gsubdetailid5 = models.CharField(db_column='GSubDetailID5', max_length=36, blank=True, null=True)
    gsubdetailid6 = models.CharField(db_column='GSubDetailID6', max_length=36, blank=True, null=True)
    gcurrencytypeid = models.CharField(db_column='GCurrencyTypeID', max_length=36, blank=True, null=True)
    gserialid = models.CharField(db_column='GSerialId', max_length=36, blank=True, null=True)
    gsubdetailidvat = models.CharField(db_column='GSubDetailIDVAT', max_length=36, blank=True, null=True)
    mashmolkind = models.IntegerField(db_column='MashmolKind', blank=True, null=True)
    vatkind = models.IntegerField(db_column='VATKind', blank=True, null=True)
    createdby = models.CharField(db_column='CreatedBy', max_length=36, blank=True, null=True)
    createddate = models.DateTimeField(db_column='CreatedDate', blank=True, null=True)
    tikstatus = models.IntegerField(db_column='TikStatus')
    tikdate = models.DateTimeField(db_column='TikDate', blank=True, null=True)
    tikrahgiri = models.CharField(db_column='TikRahgiri', max_length=10, db_collation='Arabic_CI_AS', blank=True, null=True)
    articletypecode = models.IntegerField(db_column='ArticleTypeCode')
    hasduplicate = models.BooleanField(db_column='HasDuplicate')
    taxid = models.CharField(db_column='TaxId', max_length=50, db_collation='Arabic_CI_AS', blank=True, null=True)
    taxiddatetime = models.DateTimeField(db_column='TaxIdDateTime', blank=True, null=True)
    taxiduserid = models.CharField(db_column='TaxIdUserId', max_length=36, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'tblSanadrad'


class Tblsanad(models.Model):
    sanadid = models.IntegerField(db_column='SanadID')
    sanadno = models.CharField(db_column='SanadNo', max_length=10, db_collation='Arabic_CI_AS', blank=True, null=True)
    sanaddate = models.CharField(db_column='SanadDate', max_length=10, db_collation='Arabic_CI_AS', blank=True, null=True)
    sanaddesc = models.CharField(db_column='SanadDesc', max_length=1000, db_collation='Arabic_CI_AS', blank=True, null=True)
    operkind = models.SmallIntegerField(db_column='OperKind')
    operid = models.IntegerField(db_column='OperID', blank=True, null=True)
    status = models.CharField(db_column='Status', max_length=1, db_collation='Arabic_CI_AS', blank=True, null=True)
    createddate = models.CharField(db_column='CreatedDate', max_length=10, db_collation='Arabic_CI_AS', blank=True, null=True)
    lastupdateddate = models.CharField(db_column='LastUpdatedDate', max_length=10, db_collation='Arabic_CI_AS', blank=True, null=True)
    okdate = models.CharField(db_column='OkDate', max_length=10, db_collation='Arabic_CI_AS', blank=True, null=True)
    financialyear = models.IntegerField(db_column='FinancialYear', blank=True, null=True)
    companyyearid = models.IntegerField(db_column='CompanyYearID', blank=True, null=True)
    zamimecount = models.CharField(db_column='ZamimeCount', max_length=50, db_collation='Arabic_CI_AS', blank=True, null=True)
    goperid = models.CharField(db_column='GOperID', max_length=36, blank=True, null=True)
    gsanadid = models.CharField(db_column='GSanadID', primary_key=True, max_length=36)
    gcompanyid = models.CharField(db_column='GCompanyID', max_length=36, blank=True, null=True)
    createdby = models.CharField(db_column='CreatedBy', max_length=36, blank=True, null=True)
    lastupdatedby = models.CharField(db_column='LastUpdatedBy', max_length=36, blank=True, null=True)
    okby = models.CharField(db_column='OkBy', max_length=36, blank=True, null=True)
    sanadmosalsal = models.IntegerField(db_column='SanadMosalsal')
    sanadnote1 = models.CharField(db_column='SanadNote1', max_length=500, db_collation='Arabic_CI_AS', blank=True, null=True)
    sanadnote2 = models.CharField(db_column='SanadNote2', max_length=500, db_collation='Arabic_CI_AS', blank=True, null=True)
    sanadnote3 = models.CharField(db_column='SanadNote3', max_length=500, db_collation='Arabic_CI_AS', blank=True, null=True)
    sanadtime = models.CharField(db_column='SanadTime', max_length=5, db_collation='Arabic_CI_AS')
    ismerge = models.BooleanField(db_column='IsMerge')
    deletedby = models.CharField(db_column='DeletedBy', max_length=36, blank=True, null=True)
    deleteddate = models.CharField(db_column='DeletedDate', max_length=10, db_collation='Arabic_CI_AS', blank=True, null=True)
    taxid = models.CharField(db_column='TaxID', max_length=50, db_collation='Arabic_CI_AS', blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'tblSanad'
        unique_together = (('sanadno', 'financialyear'),)


class Salerequestmaster(models.Model):
    # 1. Change to AutoField with primary_key=True (This is an IDENTITY column in SQL Server)
    salerequestmasterid = models.AutoField(db_column='SaleRequestMasterID', primary_key=True)
    salerequestno = models.CharField(db_column='SaleRequestNo', max_length=50, db_collation='Arabic_CI_AS')
    salerequestdate = models.CharField(db_column='SaleRequestDate', max_length=10, db_collation='Arabic_CI_AS')
    receipttypecode = models.SmallIntegerField(db_column='ReceiptTypeCode', blank=True, null=True)
    salerequeststatuscode = models.SmallIntegerField(db_column='SaleRequestStatusCode')
    typesalecode = models.SmallIntegerField(db_column='TypeSaleCode', blank=True, null=True)
    transferlocationcode = models.SmallIntegerField(db_column='TransferLocationCode', blank=True, null=True)
    visitorid = models.IntegerField(db_column='VisitorID', blank=True, null=True)
    accyear = models.IntegerField(db_column='AccYear')
    userid = models.IntegerField(db_column='UserId', blank=True, null=True)
    descriptions = models.CharField(db_column='Descriptions', max_length=200, db_collation='Arabic_CI_AS', blank=True, null=True)
    
    # 2. Remove primary_key=True from gsalerequestmasterid (it is a standard GUID)
    gsalerequestmasterid = models.CharField(db_column='GSaleRequestMasterID', max_length=36)
    gcompanyid = models.CharField(db_column='GCompanyID', max_length=36, blank=True, null=True)
    totalsumefect = models.SmallIntegerField(db_column='TotalSumEfect', blank=True, null=True)
    creditduration = models.IntegerField(db_column='CreditDuration', blank=True, null=True)
    createddate = models.CharField(db_column='CreatedDate', max_length=10, db_collation='Arabic_CI_AS', blank=True, null=True)
    lastupdateddate = models.CharField(db_column='LastUpdatedDate', max_length=10, db_collation='Arabic_CI_AS', blank=True, null=True)
    okdate = models.CharField(db_column='OkDate', max_length=10, db_collation='Arabic_CI_AS', blank=True, null=True)
    atfno = models.CharField(db_column='AtfNo', max_length=50, db_collation='Arabic_CI_AS', blank=True, null=True)
    ispersonal = models.BooleanField(db_column='IsPersonal', blank=True, null=True)
    gbranchid = models.CharField(db_column='GBranchID', max_length=36, blank=True, null=True)
    gcustomerid = models.CharField(db_column='GCustomerID', max_length=36, blank=True, null=True)
    gcreatedby = models.CharField(db_column='GCreatedBy', max_length=36, blank=True, null=True)
    glastupdatedby = models.CharField(db_column='GLastUpdatedBy', max_length=36, blank=True, null=True)
    gokby = models.CharField(db_column='GOkBy', max_length=36, blank=True, null=True)
    gsubdetailid4 = models.CharField(db_column='GSubDetailID4', max_length=36, blank=True, null=True)
    gsubdetailid5 = models.CharField(db_column='GSubDetailID5', max_length=36, blank=True, null=True)
    salerequestdescript1 = models.CharField(db_column='SaleRequestDescript1', max_length=1000, db_collation='Arabic_CI_AS', blank=True, null=True)
    salerequestdescript2 = models.CharField(db_column='SaleRequestDescript2', max_length=1000, db_collation='Arabic_CI_AS', blank=True, null=True)
    salerequestdescript3 = models.CharField(db_column='SaleRequestDescript3', max_length=1000, db_collation='Arabic_CI_AS', blank=True, null=True)
    salerequestdescript4 = models.CharField(db_column='SaleRequestDescript4', max_length=1000, db_collation='Arabic_CI_AS', blank=True, null=True)
    salerequestdescript5 = models.CharField(db_column='SaleRequestDescript5', max_length=1000, db_collation='Arabic_CI_AS', blank=True, null=True)
    salerequesttypecode = models.IntegerField(db_column='SaleRequestTypeCode')
    createdtime = models.CharField(db_column='CreatedTime', max_length=8, db_collation='Arabic_CI_AS', blank=True, null=True)
    gcustvendorid = models.CharField(db_column='GCustVendorID', max_length=36, blank=True, null=True)
    gdistributorid = models.CharField(db_column='GDistributorID', max_length=36, blank=True, null=True)
    gorderstockid = models.CharField(db_column='GOrderStockID', max_length=36, blank=True, null=True)
    lastupdatedtime = models.CharField(db_column='LastUpdatedTime', max_length=8, db_collation='Arabic_CI_AS', blank=True, null=True)
    oktime = models.CharField(db_column='OkTime', max_length=8, db_collation='Arabic_CI_AS', blank=True, null=True)
    requestnumber = models.CharField(db_column='RequestNumber', max_length=10, db_collation='Arabic_CI_AS', blank=True, null=True)
    tahvildate = models.CharField(db_column='TahvilDate', max_length=10, db_collation='Arabic_CI_AS', blank=True, null=True)
    ginvid = models.CharField(db_column='GInvId', max_length=36, blank=True, null=True)
    gcontractid = models.CharField(db_column='GContractId', max_length=36, blank=True, null=True)
    centerprojectid1 = models.CharField(db_column='CenterProjectId1', max_length=36, blank=True, null=True)
    centerprojectid2 = models.CharField(db_column='CenterProjectId2', max_length=36, blank=True, null=True)
    masrafunitid = models.CharField(db_column='MasrafUnitId', max_length=36, blank=True, null=True)
    estelamno = models.CharField(db_column='EstelamNo', max_length=20, db_collation='Arabic_CI_AS', blank=True, null=True)
    estelamdate = models.CharField(db_column='EstelamDate', max_length=10, db_collation='Arabic_CI_AS', blank=True, null=True)
    gcurrencytypeid = models.CharField(db_column='GCurrencyTypeID', max_length=36, blank=True, null=True)
    currencyrate = models.DecimalField(db_column='CurrencyRate', max_digits=19, decimal_places=4)
    requestman = models.CharField(db_column='RequestMan', max_length=100, db_collation='Arabic_CI_AS', blank=True, null=True)
    faniexpiredate = models.CharField(db_column='FaniExpireDate', max_length=10, db_collation='Arabic_CI_AS', blank=True, null=True)
    maliexpiredate = models.CharField(db_column='MaliExpireDate', max_length=10, db_collation='Arabic_CI_AS', blank=True, null=True)
    mohlattahvildate = models.CharField(db_column='MohlatTahvilDate', max_length=10, db_collation='Arabic_CI_AS', blank=True, null=True)
    maintahvildate = models.CharField(db_column='MainTahvilDate', max_length=10, db_collation='Arabic_CI_AS', blank=True, null=True)
    penaltypercent = models.DecimalField(db_column='PenaltyPercent', max_digits=18, decimal_places=8, blank=True, null=True)
    penaltyprice = models.DecimalField(db_column='PenaltyPrice', max_digits=18, decimal_places=0, blank=True, null=True)
    forcevat = models.BooleanField(db_column='ForceVAT')
    cancelby = models.CharField(db_column='CancelBy', max_length=36, blank=True, null=True)
    canceldate = models.CharField(db_column='CancelDate', max_length=10, db_collation='Arabic_CI_AS', blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'SaleRequestMaster'
        unique_together = (('salerequestno', 'accyear'),)


class Salerequestdetail(models.Model):
    # 3. Change to AutoField with primary_key=True
    salerequestdetailid = models.AutoField(db_column='SaleRequestDetailID', primary_key=True)
    salerequestmasterid = models.IntegerField(db_column='SaleRequestMasterID', blank=True, null=True)
    kalaid = models.IntegerField(db_column='KalaID', blank=True, null=True)
    quantity = models.DecimalField(db_column='Quantity', max_digits=20, decimal_places=8, blank=True, null=True)
    unitprice = models.DecimalField(db_column='UnitPrice', max_digits=18, decimal_places=0)
    kalaunitid = models.IntegerField(db_column='KalaUnitID', blank=True, null=True)
    secunitquantity = models.DecimalField(db_column='SecUnitQuantity', max_digits=20, decimal_places=8, blank=True, null=True)
    secunitprice = models.DecimalField(db_column='SecUnitPrice', max_digits=18, decimal_places=0, blank=True, null=True)
    kalasecunitid = models.IntegerField(db_column='KalaSecUnitID', blank=True, null=True)
    gsalerequestdetailid = models.CharField(db_column='GSaleRequestDetailID', max_length=36)
    gcompanyid = models.CharField(db_column='GCompanyID', max_length=36, blank=True, null=True)
    othercost = models.DecimalField(db_column='OtherCost', max_digits=18, decimal_places=0, blank=True, null=True)
    discount = models.DecimalField(db_column='Discount', max_digits=18, decimal_places=0, blank=True, null=True)
    gsalerequestmasterid = models.CharField(db_column='GSaleRequestMasterID', max_length=36, blank=True, null=True)
    gkalaid = models.CharField(db_column='GKalaID', max_length=36, blank=True, null=True)
    gkalasecunitid = models.CharField(db_column='GKalaSecUnitID', max_length=36, blank=True, null=True)
    descript = models.CharField(db_column='Descript', max_length=100, db_collation='Arabic_CI_AS', blank=True, null=True)
    sefareshno = models.CharField(db_column='SefareshNo', max_length=50, db_collation='Arabic_CI_AS', blank=True, null=True)
    radyabino = models.CharField(db_column='RadyabiNo', max_length=50, db_collation='Arabic_CI_AS', blank=True, null=True)
    gawardkalaid = models.CharField(db_column='GAwardKalaID', max_length=36, blank=True, null=True)
    awardamount = models.DecimalField(db_column='AwardAmount', max_digits=20, decimal_places=8, blank=True, null=True)
    salerequestdetailstatuscode = models.SmallIntegerField(db_column='SaleRequestDetailStatusCode')
    canchangeaward = models.BooleanField(db_column='CanChangeAward')
    uniqueid = models.CharField(db_column='UniqueId', max_length=36)
    prefactoruniqueid = models.CharField(db_column='PreFactorUniqueId', max_length=36, blank=True, null=True)
    estelamno = models.CharField(db_column='EstelamNo', max_length=20, db_collation='Arabic_CI_AS', blank=True, null=True)
    estelamdate = models.CharField(db_column='EstelamDate', max_length=10, db_collation='Arabic_CI_AS', blank=True, null=True)
    estelamanswerdate = models.CharField(db_column='EstelamAnswerDate', max_length=10, db_collation='Arabic_CI_AS', blank=True, null=True)
    gcurrencytypeid = models.CharField(db_column='GCurrencyTypeID', max_length=36, blank=True, null=True)
    currencyrate = models.DecimalField(db_column='CurrencyRate', max_digits=19, decimal_places=4)
    currencyprice = models.DecimalField(db_column='CurrencyPrice', max_digits=19, decimal_places=4)
    gattributedetailid = models.CharField(db_column='GAttributeDetailID', max_length=36, blank=True, null=True)
    okby = models.CharField(db_column='OkBy', max_length=36, blank=True, null=True)
    okdate = models.CharField(db_column='OkDate', max_length=50, db_collation='Arabic_CI_AS', blank=True, null=True)
    okdesc = models.CharField(db_column='OkDesc', max_length=250, db_collation='Arabic_CI_AS', blank=True, null=True)
    reasonoknokdesc = models.CharField(db_column='ReasonOkNokDesc', max_length=250, db_collation='Arabic_CI_AS', blank=True, null=True)
    faniexpiredate = models.CharField(db_column='FaniExpireDate', max_length=10, db_collation='Arabic_CI_AS', blank=True, null=True)
    maliexpiredate = models.CharField(db_column='MaliExpireDate', max_length=10, db_collation='Arabic_CI_AS', blank=True, null=True)
    mohlattahvildate = models.CharField(db_column='MohlatTahvilDate', max_length=10, db_collation='Arabic_CI_AS', blank=True, null=True)
    maintahvildate = models.CharField(db_column='MainTahvilDate', max_length=10, db_collation='Arabic_CI_AS', blank=True, null=True)
    penaltypercent = models.DecimalField(db_column='PenaltyPercent', max_digits=18, decimal_places=8, blank=True, null=True)
    penaltyprice = models.DecimalField(db_column='PenaltyPrice', max_digits=18, decimal_places=0, blank=True, null=True)
    rowid = models.IntegerField(db_column='RowId')
    kalamojodi = models.DecimalField(db_column='KalaMojodi', max_digits=25, decimal_places=8)

    class Meta:
        managed = False
        db_table = 'SaleRequestDetail'
        unique_together = (('gsalerequestmasterid', 'gkalaid', 'descript'),)


class Salerequestdetailstatus(models.Model):
    salerequestdetailstatuscode = models.SmallIntegerField(db_column='SaleRequestDetailStatusCode', primary_key=True)
    salerequestdetailstatusname = models.CharField(db_column='SaleRequestDetailStatusName', max_length=50, db_collation='Arabic_CI_AS')

    class Meta:
        managed = False
        db_table = 'SaleRequestDetailStatus'


class Salerequesttovisitor(models.Model):
    salerequesttovisitorid = models.IntegerField(db_column='SaleRequestToVisitorId', primary_key=True)
    visitorid = models.IntegerField(db_column='VisitorID', blank=True, null=True)
    salerequestid = models.IntegerField(db_column='SaleRequestId', blank=True, null=True)
    porsant = models.DecimalField(db_column='Porsant', max_digits=18, decimal_places=2)
    istafzil5 = models.BooleanField(db_column='IsTafzil5', blank=True, null=True)
    gsalerequesttovisitorid = models.CharField(db_column='GSaleRequestToVisitorId', max_length=36)
    gcompanyid = models.CharField(db_column='GCompanyID', max_length=36, blank=True, null=True)
    gvisitorid = models.CharField(db_column='GVisitorID', max_length=36, blank=True, null=True)
    gsalerequestid = models.CharField(db_column='GSaleRequestId', max_length=36, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'SaleRequestToVisitor'


class Tblkala(models.Model):
    kalaid = models.IntegerField(db_column='KalaID')
    kalano = models.CharField(db_column='KalaNo', max_length=100, db_collation='Arabic_CI_AS', blank=True, null=True)
    kalaname = models.CharField(db_column='KalaName', max_length=200, db_collation='Arabic_CI_AS')
    vahed1 = models.CharField(max_length=10, db_collation='Arabic_CI_AS', blank=True, null=True)
    mojodictrl = models.CharField(db_column='MojodiCtrl', max_length=1, db_collation='Arabic_CI_AS')
    fanino = models.CharField(db_column='FaniNo', max_length=50, db_collation='Arabic_CI_AS', blank=True, null=True)
    peygirino = models.CharField(db_column='PeygiriNo', max_length=200, db_collation='Arabic_CI_AS', blank=True, null=True)
    length = models.CharField(db_column='Length', max_length=20, db_collation='Arabic_CI_AS', blank=True, null=True)
    high = models.CharField(db_column='High', max_length=20, db_collation='Arabic_CI_AS', blank=True, null=True)
    width = models.CharField(db_column='Width', max_length=20, db_collation='Arabic_CI_AS', blank=True, null=True)
    weight = models.CharField(db_column='Weight', max_length=20, db_collation='Arabic_CI_AS', blank=True, null=True)
    kalastatus = models.CharField(db_column='KalaStatus', max_length=1, db_collation='Arabic_CI_AS', blank=True, null=True)
    kimage = models.BinaryField(db_column='kImage', blank=True, null=True)
    height = models.IntegerField(db_column='HEIGHT', blank=True, null=True)
    scale = models.IntegerField(db_column='SCALE')
    barcode = models.CharField(db_column='barCode', max_length=50, db_collation='Arabic_CI_AS', blank=True, null=True)
    kaladesc = models.CharField(db_column='KalaDesc', max_length=1000, db_collation='Arabic_CI_AS', blank=True, null=True)
    kaladesc2 = models.CharField(db_column='KalaDesc2', max_length=1000, db_collation='Arabic_CI_AS', blank=True, null=True)
    kaladesc3 = models.CharField(db_column='KalaDesc3', max_length=1000, db_collation='Arabic_CI_AS', blank=True, null=True)
    kaladesc4 = models.CharField(db_column='KalaDesc4', max_length=1000, db_collation='Arabic_CI_AS', blank=True, null=True)
    irancode = models.CharField(db_column='IranCode', max_length=50, db_collation='Arabic_CI_AS', blank=True, null=True)
    gkalaid = models.CharField(db_column='GKalaID', primary_key=True, max_length=36)
    gcompanyid = models.CharField(db_column='GCompanyID', max_length=36, blank=True, null=True)
    gparentid = models.CharField(db_column='GParentID', max_length=36, blank=True, null=True)
    gkalaunitid = models.CharField(db_column='GKalaUnitID', max_length=36, blank=True, null=True)
    ggroupid = models.CharField(db_column='GGroupID', max_length=36, blank=True, null=True)
    invkalatypeid = models.IntegerField(db_column='InvKalaTypeID')
    kalagroup = models.BooleanField(db_column='KalaGroup')
    havewarranty = models.BooleanField(db_column='HaveWarranty')
    havedaghi = models.BooleanField(db_column='HaveDaghi')
    warrantymonth = models.IntegerField(db_column='WarrantyMonth')
    serialforce = models.BooleanField(db_column='SerialForce')
    serialpazir = models.BooleanField(db_column='SerialPazir')
    saleinternet = models.BooleanField(db_column='SaleInternet')
    kalabatch = models.DecimalField(db_column='KalaBatch', max_digits=20, decimal_places=8, blank=True, null=True)
    saleintablet = models.BooleanField(db_column='SaleInTablet')
    tabletorder = models.IntegerField(db_column='TabletOrder')
    active = models.BooleanField(db_column='Active')
    zaribtablet = models.IntegerField(db_column='ZaribTablet', blank=True, null=True)
    effective = models.BooleanField(db_column='Effective')
    maliat = models.BooleanField(db_column='Maliat')
    gvarietyid = models.CharField(db_column='GVarietyId', max_length=36, blank=True, null=True)
    gbrandid = models.CharField(db_column='GBrandId', max_length=36, blank=True, null=True)
    gmodelkalaid = models.CharField(db_column='GModelKalaId', max_length=36, blank=True, null=True)
    gcountryid = models.CharField(db_column='GCountryId', max_length=36, blank=True, null=True)
    kalalabel = models.CharField(db_column='KalaLabel', max_length=1000, db_collation='Arabic_CI_AS', blank=True, null=True)
    selprice = models.DecimalField(db_column='SelPrice', max_digits=18, decimal_places=0, blank=True, null=True)
    buyprice = models.DecimalField(db_column='BuyPrice', max_digits=18, decimal_places=0, blank=True, null=True)
    amount = models.DecimalField(db_column='Amount', max_digits=18, decimal_places=0, blank=True, null=True)
    yektaidentity = models.CharField(db_column='YektaIdentity', max_length=50, db_collation='Arabic_CI_AS', blank=True, null=True)
    yektavahed = models.CharField(db_column='YektaVahed', max_length=20, db_collation='Arabic_CI_AS', blank=True, null=True)
    yektaname = models.CharField(db_column='YektaName', max_length=400, db_collation='Arabic_CI_AS', blank=True, null=True)
    yektadedicate = models.CharField(db_column='YektaDedicate', max_length=50, db_collation='Arabic_CI_AS', blank=True, null=True)
    yektadedicatename = models.CharField(db_column='YektaDedicateName', max_length=400, db_collation='Arabic_CI_AS', blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'tblKala'


class Salerequeststatus(models.Model):
    salerequeststatuscode = models.SmallIntegerField(db_column='SaleRequestStatusCode', primary_key=True)  # Field name made lowercase.
    salerequeststatusname = models.CharField(db_column='SaleRequestStatusName', max_length=50, db_collation='Arabic_CI_AS')  # Field name made lowercase.
    gcompanyid = models.CharField(db_column='GCompanyID', max_length=36, blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'SaleRequestStatus'


class Statementprice(models.Model):
    statementpriceid = models.IntegerField(db_column='StatementPriceID')  # Field name made lowercase.
    statementpricemainid = models.IntegerField(db_column='StatementPriceMainID', blank=True, null=True)  # Field name made lowercase.
    kalaid = models.IntegerField(db_column='KalaID', blank=True, null=True)  # Field name made lowercase.
    customergroupid = models.IntegerField(db_column='CustomerGroupID', blank=True, null=True)  # Field name made lowercase.
    fromquantity = models.DecimalField(db_column='FromQuantity', max_digits=18, decimal_places=0)  # Field name made lowercase.
    toquantity = models.DecimalField(db_column='ToQuantity', max_digits=18, decimal_places=0)  # Field name made lowercase.
    price = models.DecimalField(db_column='Price', max_digits=18, decimal_places=0)  # Field name made lowercase.
    pricetypecode = models.SmallIntegerField(db_column='PriceTypeCode')  # Field name made lowercase.
    gcompanyid = models.CharField(db_column='GCompanyID', max_length=36, blank=True, null=True)  # Field name made lowercase.
    gstatementpriceid = models.CharField(db_column='GStatementPriceID', max_length=36)  # Field name made lowercase.
    gstatementpricemainid = models.CharField(db_column='GStatementPriceMainID', max_length=36, blank=True, null=True)  # Field name made lowercase.
    gcustomergroupid = models.CharField(db_column='GCustomerGroupID', max_length=36, blank=True, null=True)  # Field name made lowercase.
    gkalaid = models.CharField(db_column='GKalaID', max_length=36, blank=True, null=True)  # Field name made lowercase.
    pricearz = models.DecimalField(db_column='PriceArz', max_digits=18, decimal_places=4, blank=True, null=True)  # Field name made lowercase.
    spno = models.CharField(db_column='SpNo', max_length=50, db_collation='Arabic_CI_AS', blank=True, null=True)  # Field name made lowercase.
    gkalasecunitid = models.CharField(db_column='GKalaSecUnitID', max_length=36, blank=True, null=True)  # Field name made lowercase.
    secunitprice = models.DecimalField(db_column='SecUnitPrice', max_digits=18, decimal_places=0, blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'StatementPrice'


class TuaUser(models.Model):
    uid = models.CharField(db_column='uID', max_length=50, db_collation='Arabic_CI_AS', blank=True, null=True)  # Field name made lowercase.
    upw = models.CharField(db_column='uPW', max_length=50, db_collation='Arabic_CI_AS', blank=True, null=True)  # Field name made lowercase.
    uname = models.CharField(db_column='uName', max_length=50, db_collation='Arabic_CI_AS', blank=True, null=True)  # Field name made lowercase.
    utitle = models.CharField(db_column='uTitle', max_length=50, db_collation='Arabic_CI_AS', blank=True, null=True)  # Field name made lowercase.
    uactive = models.BooleanField(db_column='uActive')  # Field name made lowercase.
    udate = models.CharField(db_column='uDate', max_length=10, db_collation='Arabic_CI_AS', blank=True, null=True)  # Field name made lowercase.
    ucode = models.IntegerField(db_column='uCode')  # Field name made lowercase.
    isadmin = models.BooleanField(db_column='isAdmin', blank=True, null=True)  # Field name made lowercase.
    persheet = models.CharField(db_column='PerSheet', max_length=100, db_collation='Arabic_CI_AS', blank=True, null=True)  # Field name made lowercase.
    hasmessage = models.BooleanField(db_column='HasMessage', blank=True, null=True)  # Field name made lowercase.
    messagekind = models.CharField(db_column='MessageKind', max_length=50, db_collation='Arabic_CI_AS', blank=True, null=True)  # Field name made lowercase.
    alarmtypecode = models.CharField(db_column='AlarmTypeCode', max_length=50, db_collation='Arabic_CI_AS', blank=True, null=True)  # Field name made lowercase.
    gucode = models.CharField(db_column='GuCode', primary_key=True, max_length=36)  # Field name made lowercase.
    gcompanyid = models.CharField(db_column='GCompanyID', max_length=36, blank=True, null=True)  # Field name made lowercase.
    emailaddress = models.CharField(db_column='EmailAddress', max_length=150, db_collation='Arabic_CI_AS', blank=True, null=True)  # Field name made lowercase.
    emailpass = models.CharField(db_column='EmailPass', max_length=50, db_collation='Arabic_CI_AS', blank=True, null=True)  # Field name made lowercase.
    hasletter = models.BooleanField(db_column='HasLetter', blank=True, null=True)  # Field name made lowercase.
    havenewversion = models.BooleanField(db_column='HaveNewVersion')  # Field name made lowercase.
    dailyalarm = models.BooleanField(db_column='DailyAlarm')  # Field name made lowercase.
    lastalarmseendate = models.CharField(db_column='LastAlarmSeenDate', max_length=10, db_collation='Arabic_CI_AS', blank=True, null=True)  # Field name made lowercase.
    csmobile = models.CharField(db_column='CSMobile', max_length=11, db_collation='Arabic_CI_AS', blank=True, null=True)  # Field name made lowercase.
    cspassword = models.CharField(db_column='CSPassword', max_length=50, db_collation='Arabic_CI_AS', blank=True, null=True)  # Field name made lowercase.
    uaddress = models.CharField(db_column='uAddress', max_length=200, db_collation='Arabic_CI_AS', blank=True, null=True)  # Field name made lowercase.
    ubirthdate = models.CharField(db_column='uBirthDate', max_length=10, db_collation='Arabic_CI_AS', blank=True, null=True)  # Field name made lowercase.
    pwdtypecode = models.IntegerField(db_column='PwdTypeCode')  # Field name made lowercase.
    canbackedup = models.BooleanField(db_column='CanBackedUp', blank=True, null=True)  # Field name made lowercase.
    wpu = models.CharField(db_column='WPU', max_length=10, db_collation='Arabic_CI_AS', blank=True, null=True)  # Field name made lowercase.
    pluspass = models.CharField(max_length=50, db_collation='Arabic_CI_AS', blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'TUA_User'

