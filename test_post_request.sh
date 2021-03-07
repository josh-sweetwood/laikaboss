#!/bin/sh

curl -X POST --data-binary @./LaikaBOSS_Whitepaper.pdf 'http://localhost/scan?filename=./LaikaBOSS_Whitepaper.pdf&ephID=4321&uniqID=1234&contentType=&timestamp=1978.06.17%2009:09:09&source=http&origRootUID=1&extMetaData=stuff&level=3'
