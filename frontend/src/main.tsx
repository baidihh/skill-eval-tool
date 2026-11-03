import React from 'react';
import ReactDOM from 'react-dom/client';
import { ConfigProvider, App as AntApp } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import App from './App';
import './style.css';
ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><ConfigProvider locale={zhCN} theme={{token:{colorPrimary:'#147d74',borderRadius:7,colorText:'#223838',fontFamily:'"PingFang SC", "Microsoft YaHei", sans-serif',colorBgLayout:'#f4f5f0'},components:{Table:{headerBg:'#f4f6f3',headerColor:'#6c7b76'},Button:{controlHeight:36},Card:{paddingLG:24}}}}><AntApp><App/></AntApp></ConfigProvider></React.StrictMode>);
