import streamlit as st
import pandas as pd
import numpy as np
import io
import folium
import streamlit.components.v1 as components

# ---------------------------------------------------------
# การตั้งค่าหน้าเว็บ Streamlit
# ---------------------------------------------------------
st.set_page_config(page_title="TMS Route Optimization (Savings Algorithm)", layout="wide")
st.title("🚛 ระบบบริหารจัดการเส้นทางและลดต้นทุนขนส่ง (TMS)")
st.markdown("""
ระบบนี้ใช้ **Savings Algorithm** คำนวณเส้นทางที่ประหยัดที่สุด (ดึงระยะทางตรงจาก Distance Matrix ของไฟล์ Excel)
""")

# ---------------------------------------------------------
# แถบด้านข้าง (Sidebar) สำหรับตั้งค่าพารามิเตอร์
# ---------------------------------------------------------
st.sidebar.header("⚙️ ตั้งค่าพารามิเตอร์การขนส่ง")
vehicle_capacity = st.sidebar.number_input("ความจุรถสูงสุด (กก./คัน)", value=3500)
cost_per_km = st.sidebar.number_input("ต้นทุนน้ำมัน (บาท/กม.)", value=5.7143, format="%.4f")
original_cost = st.sidebar.number_input("ต้นทุนเดิมเพื่อเปรียบเทียบ (บาท)", value=27904.72) 

uploaded_file = st.sidebar.file_uploader("📂 อัปโหลดไฟล์ Excel ของลูกค้า (รูปแบบ TMS_Savings 2)", type=['xlsx'])

if uploaded_file is not None:
    try:
        # ---------------------------------------------------------
        # 1. อ่านข้อมูลพิกัด (สำหรับการปักหมุดแผนที่)
        # ---------------------------------------------------------
        df_dist = pd.read_excel(uploaded_file, sheet_name='1.Distance Matrix')
        df_dist_data = df_dist.iloc[2:].reset_index(drop=True)
        
        df_coords = df_dist_data.iloc[:, 0:3].copy()
        df_coords.columns = ['ชื่อลูกค้า', 'Latitude', 'Longitude']
        df_coords['Latitude'] = pd.to_numeric(df_coords['Latitude'], errors='coerce')
        df_coords['Longitude'] = pd.to_numeric(df_coords['Longitude'], errors='coerce')

        # พิกัดโรงงาน
        depot_row = df_coords[df_coords['ชื่อลูกค้า'] == 'โรงงาน (จุดเริ่มต้น)']
        if not depot_row.empty:
            depot_lat = depot_row['Latitude'].values[0]
            depot_lon = depot_row['Longitude'].values[0]
        else:
            depot_lat, depot_lon = 13.52596, 100.173329

        # ---------------------------------------------------------
        # 2. อ่าน Distance Matrix ตรงๆ จาก Excel (เพื่อให้ต้นทุนเป๊ะ)
        # ---------------------------------------------------------
        matrix_values = df_dist_data.iloc[:, 3:].copy()
        matrix_values = matrix_values.replace('-', np.nan).astype(float).values
        matrix_values[np.isnan(matrix_values)] = 999999.0 # จุดออนไลน์ไม่มีระยะทาง ให้ข้าม

        # ---------------------------------------------------------
        # 3. แมป Demand และคัดกรองเฉพาะ "จัดเส้นทางรถ"
        # ---------------------------------------------------------
        df_demand = pd.read_excel(uploaded_file, sheet_name='Demand Mapping')
        df_demand = df_demand[['ชื่อร้าน/Node', 'Demand (กก.)', 'สถานะ TMS']]

        df_coords = df_coords.merge(df_demand, left_on='ชื่อลูกค้า', right_on='ชื่อร้าน/Node', how='left')
        df_coords['Demand (กก.)'] = df_coords['Demand (กก.)'].fillna(0)

        valid_indices = [] # เก็บ Index ของร้านค้าที่จะจัดส่งจริง (ตัด Depot ออกก่อน)
        for idx, row in df_coords.iterrows():
            if idx == 0:
                continue # ข้ามโรงงาน
            if row['สถานะ TMS'] == 'จัดเส้นทางรถ':
                valid_indices.append(idx)
                
        customers = []
        for c_i in valid_indices:
            customers.append(df_coords.iloc[c_i].to_dict())

        n = len(customers)
        st.success(f"โหลดข้อมูลสำเร็จ: พบจุดส่ง {n} จุด | ยอด Demand รวม {sum([c['Demand (กก.)'] for c in customers]):,.0f} กก.")
        
        # ---------------------------------------------------------
        # 4. สร้าง Matrix เฉพาะลูกค้าที่จัดเส้นทาง
        # ---------------------------------------------------------
        dist_matrix = np.zeros((n + 1, n + 1))
        for i in range(n):
            c_i = valid_indices[i]
            dist_matrix[0][i+1] = matrix_values[0, c_i]
            dist_matrix[i+1][0] = matrix_values[c_i, 0]
            for j in range(n):
                if i != j:
                    c_j = valid_indices[j]
                    dist_matrix[i+1][j+1] = matrix_values[c_i, c_j]

        # คำนวณ Savings
        savings = []
        for i in range(1, n + 1):
            for j in range(i + 1, n + 1):
                save_val = dist_matrix[0][i] + dist_matrix[0][j] - dist_matrix[i][j]
                savings.append({
                    'Node_i': i,
                    'Node_j': j,
                    'Customer_i': customers[i-1]['ชื่อลูกค้า'],
                    'Customer_j': customers[j-1]['ชื่อลูกค้า'],
                    'Saving_Distance': save_val
                })
        
        df_savings = pd.DataFrame(savings).sort_values(by='Saving_Distance', ascending=False).reset_index(drop=True)
        
        # ---------------------------------------------------------
        # 5. Routing Algorithm
        # ---------------------------------------------------------
        routes = [[i] for i in range(1, n + 1)] 
        
        def get_route_idx(node):
            for idx, route in enumerate(routes):
                if node in route:
                    return idx
            return -1

        for _, row in df_savings.iterrows():
            i, j = int(row['Node_i']), int(row['Node_j'])
            route_i_idx = get_route_idx(i)
            route_j_idx = get_route_idx(j)
            
            if route_i_idx != route_j_idx:
                route_i = routes[route_i_idx]
                route_j = routes[route_j_idx]
                
                if (route_i[0] == i or route_i[-1] == i) and (route_j[0] == j or route_j[-1] == j):
                    total_demand = sum([customers[node-1]['Demand (กก.)'] for node in route_i]) + \
                                   sum([customers[node-1]['Demand (กก.)'] for node in route_j])
                    
                    if total_demand <= vehicle_capacity:
                        if route_i[0] == i and route_j[-1] == j:
                            new_route = route_j + route_i
                        elif route_i[-1] == i and route_j[0] == j:
                            new_route = route_i + route_j
                        elif route_i[-1] == i and route_j[-1] == j:
                            new_route = route_i + route_j[::-1]
                        elif route_i[0] == i and route_j[0] == j:
                            new_route = route_i[::-1] + route_j
                            
                        routes.pop(max(route_i_idx, route_j_idx))
                        routes.pop(min(route_i_idx, route_j_idx))
                        routes.append(new_route)

        # ---------------------------------------------------------
        # 6. สรุปผลลัพธ์
        # ---------------------------------------------------------
        total_distance = 0
        route_summaries = []
        
        for idx, route in enumerate(routes):
            route_dist = dist_matrix[0][route[0]]
            route_demand = sum([customers[node-1]['Demand (กก.)'] for node in route])
            path_names = ["โรงงาน"]
            
            for k in range(len(route) - 1):
                route_dist += dist_matrix[route[k]][route[k+1]]
                path_names.append(customers[route[k]-1]['ชื่อลูกค้า'])
            
            path_names.append(customers[route[-1]-1]['ชื่อลูกค้า'])
            path_names.append("โรงงาน")
            route_dist += dist_matrix[route[-1]][0] 
            total_distance += route_dist
            
            route_summaries.append({
                "คันที่": f"คันที่ {idx + 1:02d}",
                "ลำดับเส้นทาง": " ➔ ".join(path_names),
                "ระยะทาง (กม.)": round(route_dist, 2),
                "Demand รวม (กก.)": round(route_demand, 2),
                "% การใช้รถ": f"{round((route_demand/vehicle_capacity)*100, 1)}%"
            })
            
        df_routes = pd.DataFrame(route_summaries)
        optimized_cost = total_distance * cost_per_km
        cost_saving = original_cost - optimized_cost

        # ================= Dashboard =================
        st.subheader("📊 เปรียบเทียบผลลัพธ์การลดต้นทุน")
        col1, col2, col3 = st.columns(3)
        col1.metric("ต้นทุนเดิม (โดยประมาณ)", f"{original_cost:,.2f} ฿")
        col2.metric("ต้นทุนใหม่ (Optimized)", f"{optimized_cost:,.2f} ฿", delta=f"-{cost_saving:,.2f} ฿")
        col3.metric("ระยะทางรวมใหม่", f"{total_distance:,.2f} กม.")
        
        # ================= แผนที่ =================
        st.subheader("🗺️ แผนที่เส้นทางการจัดส่ง")
        map_colors = ['blue', 'green', 'purple', 'orange', 'darkred', 'lightred', 
                      'beige', 'darkblue', 'darkgreen', 'cadetblue', 'darkpurple', 'pink']
        
        m = folium.Map(location=[depot_lat, depot_lon], zoom_start=6)
        
        folium.Marker(
            [depot_lat, depot_lon],
            popup="<b>โรงงาน</b>",
            icon=folium.Icon(color="red", icon="home", prefix='fa')
        ).add_to(m)
        
        for idx, route in enumerate(routes):
            color = map_colors[idx % len(map_colors)]
            route_coords = [[depot_lat, depot_lon]]
            
            for node in route:
                cust = customers[node-1]
                lat, lon = cust['Latitude'], cust['Longitude']
                if not pd.isna(lat) and not pd.isna(lon):
                    route_coords.append([lat, lon])
                    folium.Marker(
                        [lat, lon],
                        popup=f"<b>{cust['ชื่อลูกค้า']}</b><br>Demand: {cust['Demand (กก.)']} กก.",
                        icon=folium.Icon(color=color, icon="info-sign")
                    ).add_to(m)
                
            route_coords.append([depot_lat, depot_lon])
            
            # กรองค่า NaN ออกก่อนลากเส้น
            valid_coords = [c for c in route_coords if not pd.isna(c[0])]
            if len(valid_coords) > 1:
                folium.PolyLine(valid_coords, color=color, weight=3, opacity=0.8).add_to(m)
            
        map_html = m._repr_html_()
        components.html(map_html, height=600, width=1200)

        # ================= ตารางสรุป =================
        st.subheader("📍 สรุปเส้นทางเดินรถ (Optimized Routes)")
        st.dataframe(df_routes, use_container_width=True)

        st.subheader("🧮 ตาราง Savings Matrix")
        st.dataframe(df_savings, use_container_width=True)

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_routes.to_excel(writer, sheet_name='Optimized Routes', index=False)
            df_savings.to_excel(writer, sheet_name='Matrix Saving Algorithm', index=False)
            
        excel_data = output.getvalue()
        
        st.download_button(
            label="📥 ดาวน์โหลดผลลัพธ์เป็น Excel",
            data=excel_data,
            file_name="Optimized_Routing_Result.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาด: {e}")
else:
    st.info("กรุณาอัปโหลดไฟล์ Excel ของคุณที่แถบด้านซ้ายมือเพื่อเริ่มการวิเคราะห์")
