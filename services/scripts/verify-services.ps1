# Replaced by verify-services.py
# This stub forwards to the Python script so old callers still work.
$Host.UI.RawUI.WindowTitle = 'verify-services'
& python services/scripts/verify-services.py @args
exit $LASTEXITCODE

