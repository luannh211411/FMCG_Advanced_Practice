# Open Modeling Questions

1. Should Distributor be represented as a conformed dimension generated from distinct DistributorID values, given that no standalone distributor source exists?
2. Should the model expose both a raw promotion applicability bridge and a single attributed promotion per sale? The source rules are date + category + channel and promotion overlaps exist.
3. Are sales reps and customer assignments intended to be current-state attributes only, or should historical changes be tracked? No effective-dated customer history is available.
4. Should return measures be reported by ReturnDate, original sale Date, or both? The model should retain both role-playing date keys/attributes to avoid ambiguity.
5. Should inventory be reported as end-of-period/latest snapshot, average snapshot, or point-in-time only? Inventory must not be summed across snapshot dates.
6. Are `Month` target values first-of-month dates by contract? Current data is consistently represented as monthly dates.
