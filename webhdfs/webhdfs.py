import sys, os
import stat
import httplib
import urlparse
import json

import logging

__all__ = [
    "WebHDFS", "WebHDFSResponse"
    ]


logging.basicConfig(level=logging.DEBUG, datefmt='%m/%d/%Y %I:%M:%S %p',
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(name='webhdfs')

WEBHDFS_CONTEXT_ROOT="/webhdfs/v1"

class WebHDFS(object):       
    """ Class for accessing HDFS via WebHDFS 
    
        To enable WebHDFS in your Hadoop Installation add the following configuration
        to your hdfs_site.xml (requires Hadoop >0.20.205.0):
        
        <property>
             <name>dfs.webhdfs.enabled</name>
             <value>true</value>
        </property>  
    
        see: https://issues.apache.org/jira/secure/attachment/12500090/WebHdfsAPI20111020.pdf
    """
    
    def __init__(self, namenode_host, namenode_port, hdfs_username):
        self.namenode_host=namenode_host
        self.namenode_port = namenode_port
        self.username = hdfs_username
        
    
    def mkDir(self, path):
        url_path = WEBHDFS_CONTEXT_ROOT + path +'?op=MKDIRS&user.name='+self.username
        logger.debug("Create directory: " + url_path)
        httpClient = self.__getNameNodeHTTPClient()
        httpClient.request('PUT', url_path , headers={})
        response = httpClient.getresponse()
        logger.debug("HTTP Response: %d, %s"%(response.status, response.reason))
        httpClient.close()
        
    def delete(self, path, recursive = False):
        url_path = WEBHDFS_CONTEXT_ROOT + path +'?op=DELETE&recursive=' + ('true' if recursive else 'false') + '&user.name='+self.username
        logger.debug("Delete directory: " + url_path)
        httpClient = self.__getNameNodeHTTPClient()
        httpClient.request('DELETE', url_path , headers={})
        response = httpClient.getresponse()
        logger.debug("HTTP Response: %d, %s"%(response.status, response.reason))
        httpClient.close()
        
    def rmDir(self, path):
        self.delete(path, recursive = True)
     
    def copyToHDFS(self, source_path, target_path, replication=1, overwrite=False):
        url_path = WEBHDFS_CONTEXT_ROOT + target_path + '?op=CREATE&overwrite=' + ('true' if overwrite else 'false') +\
                                                        '&replication=' + str(replication) + '&user.name='+self.username
        httpClient = self.__getNameNodeHTTPClient()
        httpClient.request('PUT', url_path , headers={})
        response = httpClient.getresponse()
        logger.debug("HTTP Response: response.status = '%d',  response.reason = '%s', response.msg = '%s'"%(response.status, response.reason, response.msg))
        redirect_location = response.msg["location"]
        logger.debug("HTTP Location: %s"%(redirect_location))
        result = urlparse.urlparse(redirect_location)
        redirect_host = result.netloc[:result.netloc.index(":")]
        redirect_port = result.netloc[(result.netloc.index(":")+1):]
        # Bug in WebHDFS 0.20.205 => requires param otherwise a NullPointerException is thrown
        redirect_path = result.path + "?" + result.query 
            
        logger.debug("Send redirect to: host: %s, port: %s, path: %s "%(redirect_host, redirect_port, redirect_path))
        fileUploadClient = httplib.HTTPConnection(redirect_host, 
                                                  redirect_port, timeout=600)
        # This requires currently Python 2.6 or higher
        fileUploadClient.request('PUT', redirect_path, open(source_path, "rb"), headers={})
        response = fileUploadClient.getresponse()
        logger.debug("HTTP Response: %d, %s"%(response.status, response.reason))
        httpClient.close()
        fileUploadClient.close()
        return response

    def appendToHDFS(self, source_path, target_path):
        url_path = WEBHDFS_CONTEXT_ROOT + target_path + '?op=APPEND&user.name='+self.username
        
        httpClient = self.__getNameNodeHTTPClient()
        httpClient.request('POST', url_path , headers={})
        response = httpClient.getresponse()
        logger.debug("HTTP Response: response.status = '%d',  response.reason = '%s', response.msg = '%s'"%(response.status, response.reason, response.msg))
        redirect_location = response.msg["location"]
        logger.debug("HTTP Location: %s"%(redirect_location))
        result = urlparse.urlparse(redirect_location)
        redirect_host = result.netloc[:result.netloc.index(":")]
        redirect_port = result.netloc[(result.netloc.index(":")+1):]
        # Bug in WebHDFS 0.20.205 => requires param otherwise a NullPointerException is thrown
        redirect_path = result.path + "?" + result.query
            
        logger.debug("Send redirect to: host: %s, port: %s, path: %s "%(redirect_host, redirect_port, redirect_path))
        fileUploadClient = httplib.HTTPConnection(redirect_host, 
                                                  redirect_port, timeout=600)
        # This requires currently Python 2.6 or higher
        fileUploadClient.request('POST', redirect_path, open(source_path, "rb"), headers={})
        response = fileUploadClient.getresponse()
        logger.debug("HTTP Response: %d, %s"%(response.status, response.reason))
        httpClient.close()
        fileUploadClient.close()
        return response

    def copyFromHDFS(self, source_path, target_path, overwrite=False):
        if os.path.isfile(target_path) and overwrite == False:
            return WebHDFSResponse(403, 'File already exists')
            
        url_path = WEBHDFS_CONTEXT_ROOT + source_path+'?op=OPEN&user.name='+self.username
        logger.debug("GET URL: %s"%url_path)
        httpClient = self.__getNameNodeHTTPClient()
        httpClient.request('GET', url_path , headers={})
        response = httpClient.getresponse()
        # if file is empty GET returns a response with length == NONE and
        # no msg["location"]
        if response.length!=None:
            msg = response.msg
            redirect_location = msg["location"]
            logger.debug("HTTP Response: %d, %s"%(response.status, response.reason))
            logger.debug("HTTP Location: %s"%(redirect_location))
            result = urlparse.urlparse(redirect_location)
            redirect_host = result.netloc[:result.netloc.index(":")]
            redirect_port = result.netloc[(result.netloc.index(":")+1):]
            
            redirect_path = result.path + "?" + result.query  
                
            logger.debug("Send redirect to: host: %s, port: %s, path: %s "%(redirect_host, redirect_port, redirect_path))
            fileDownloadClient = httplib.HTTPConnection(redirect_host, 
                                                      redirect_port, timeout=600)
            
            fileDownloadClient.request('GET', redirect_path, headers={})
            response = fileDownloadClient.getresponse()
            logger.debug("HTTP Response: %d, %s"%(response.status, response.reason))
            
            # Write data to file
            rcv_buf_size = 1024*1024
            
            target_file = open(target_path, "wb")
            while True : 
                resp = response.read(rcv_buf_size)
                if len(resp) == 0 :
                    break
                target_file.write(resp)
                
            target_file.close()
            fileDownloadClient.close()
        else:
            target_file = open(target_path, "wb")
            target_file.close()
            
        httpClient.close()        
        return response
     
    def listDir(self, path):
        url_path = WEBHDFS_CONTEXT_ROOT +path+'?op=LISTSTATUS&user.name='+self.username
        logger.debug("List directory: " + url_path)
        httpClient = self.__getNameNodeHTTPClient()
        httpClient.request('GET', url_path , headers={})
        response = httpClient.getresponse()
        logger.debug("HTTP Response: %d, %s"%(response.status, response.reason))
        data_dict = json.loads(response.read())
        logger.debug("Data: " + str(data_dict))
        files=[]        
        for i in data_dict["FileStatuses"]["FileStatus"]:
            logger.debug(i["type"] + ": " + i["pathSuffix"]) 
            files.append(i["pathSuffix"])        
        httpClient.close()
        return files

    def listDirEx(self, path):
        url_path = WEBHDFS_CONTEXT_ROOT +path+'?op=LISTSTATUS&user.name='+self.username
        logger.debug("List directory: " + url_path)
        httpClient = self.__getNameNodeHTTPClient()
        httpClient.request('GET', url_path , headers={})
        response = httpClient.getresponse()
        logger.debug("HTTP Response: %d, %s"%(response.status, response.reason))
        data_dict = json.loads(response.read())
        logger.debug("Data: " + str(data_dict))
        return  data_dict["FileStatuses"]["FileStatus"]

    def getHomeDir (self):
        url_path = WEBHDFS_CONTEXT_ROOT + '?op=GETHOMEDIRECTORY&user.name='+self.username
        httpClient = self.__getNameNodeHTTPClient()
        httpClient.request('GET', url_path , headers={})
        response = httpClient.getresponse()
        data_dict = json.loads(response.read())
        httpClient.close()
        return data_dict['Path']
    
    def __getNameNodeHTTPClient(self):
        httpClient = httplib.HTTPConnection(self.namenode_host, 
                                            self.namenode_port, 
                                                       timeout=600)
        return httpClient
    
class WebHDFSResponse(object):
    def __init__(self, status, reason):
        self.status = status
        self.reason = reason
    
    
if __name__ == "__main__":      
    webhdfs = WebHDFS("storm0", 50070, "azhigimont")
    webhdfs.mkDir("/user/azhigimont/tmp")
    webhdfs.copyToHDFS("c:/temp/test.json", "/user/azhigimont/tmp/test.json", overwrite = True)
    webhdfs.copyFromHDFS("/user/azhigimont/tmp/test.json",  "c:/temp/test1.json", overwrite = True)
    webhdfs.listDir("/user/azhigimont/tmp")
    webhdfs.delete("/user/azhigimont/tmp", recursive = True)
